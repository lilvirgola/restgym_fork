import common
import socket
import random
import threading
import time
import psutil
import sys
import os
import json
import yaml
from rich.progress import Progress
from rich import print

MINIMUM_CPUS = 4
MINIMUM_RAM_GB = 4
TIME_BUDGET_MINS = 60

# CAMPAIGN: mutation testing configuration
MUTATION_ENABLED = True
CAMPAIGN_SEED = 42
CAMPAIGN_BUDGET = 0              # 0 = all campaigns
CAMPAIGN_REPETITIONS = 1

specification_volumes = {}

def read_config():
    with open(f'{common.RESTGYM_BASE_DIR}/restgym-config.yml') as stream:
        try:
            config = yaml.safe_load(stream)
            global MINIMUM_CPUS, MINIMUM_RAM_GB, TIME_BUDGET_MINS
            MINIMUM_RAM_GB = int(config['minimum_ram_gb'])
            MINIMUM_CPUS = int(config['minimum_cpus'])
            TIME_BUDGET_MINS = int(config['time_budget_mins'])

            global MUTATION_ENABLED, CAMPAIGN_SEED, CAMPAIGN_BUDGET, CAMPAIGN_REPETITIONS
            MUTATION_ENABLED = config.get('mutation_enabled', True)
            CAMPAIGN_SEED = int(config.get('campaign_seed', 42))
            CAMPAIGN_BUDGET = int(config.get('campaign_budget', 0))
            CAMPAIGN_REPETITIONS = int(config.get('campaign_repetitions', 1))
        except yaml.YAMLError as exc:
            print("Could not parse RESTgym configuration file. Continuing with default configuration.")
            print(exc)

def check_tcp_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return not s.connect_ex(('localhost', port)) == 0

def get_random_free_tcp_port():
    remaining_attempts = 1000
    while remaining_attempts > 0:
        candidate_port = random.randrange(10_000, 60_000)
        if check_tcp_port(candidate_port):
            return candidate_port
        remaining_attempts -= 1
    print("[red]ERROR[/red]: could not find a free TCP port for the API.")
    sys.exit(1)

def load_campaign_manifest(api):
    manifest_path = f"{common.RESTGYM_BASE_DIR}/apis/{api}/campaigns/manifest.jsonl"
    if not os.path.exists(manifest_path):
        return []
    campaigns = []
    with open(manifest_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                campaigns.append(json.loads(line))
    return campaigns

def select_campaigns_for_api(api):
    campaigns = load_campaign_manifest(api)
    if not campaigns:
        return []
    baseline = None
    mutants = []
    for c in campaigns:
        if c.get("mode") == "baseline":
            baseline = c
        else:
            mutants.append(c)
    rng = random.Random(CAMPAIGN_SEED)
    rng.shuffle(mutants)
    if CAMPAIGN_BUDGET > 0:
        selected_mutants = mutants[: max(0, CAMPAIGN_BUDGET - 1)]
    else:
        selected_mutants = mutants
    selected = []
    if baseline:
        selected.append(baseline)
    selected.extend(selected_mutants)
    return selected

def count_completed_campaign_runs(api, tool, campaign_id):
    # Since we use flat structure, we must look inside runs to check their campaign.json
    base_dir = f"{common.RESTGYM_BASE_DIR}/results/{api}/{tool}"
    if not os.path.exists(base_dir):
        return 0
    count = 0
    for run_dir in os.listdir(base_dir):
        run_path = os.path.join(base_dir, run_dir)
        if not os.path.isdir(run_path): continue
        
        campaign_file = os.path.join(run_path, "campaign.json")
        completed_file = os.path.join(run_path, "completed.txt")
        
        if os.path.exists(completed_file) and os.path.exists(campaign_file):
            try:
                with open(campaign_file, 'r') as f:
                    data = json.load(f)
                    if data.get("campaign_id") == campaign_id:
                        count += 1
            except:
                pass
    return count

def check_campaigns_exist():
    missing = []
    for api in common.get_apis():
        if not common.check_enabled('api', api): continue
        manifest_path = f"{common.RESTGYM_BASE_DIR}/apis/{api}/campaigns/manifest.jsonl"
        if not os.path.exists(manifest_path):
            missing.append(api)
    return missing

def compute_remaining_runs_campaign():
    remaining_runs = []
    apis = common.get_apis()
    print("Enabled APIs:", apis)
    tools = common.get_tools()
    print("Enabled tools:", tools)
    for api in apis:
        campaigns = select_campaigns_for_api(api)
        if not campaigns:
            print(f"  [yellow]WARN[/yellow] No campaigns for {api}. Skipping.")
            continue
        print(f"  {api}: {len(campaigns)} campaigns selected.")
        for tool in tools:
            for campaign in campaigns:
                campaign_id = campaign["campaign_id"]
                completed = count_completed_campaign_runs(api, tool, campaign_id)
                reps_needed = CAMPAIGN_REPETITIONS - completed
                for _ in range(max(0, reps_needed)):
                    remaining_runs.append({
                        'api': api,
                        'tool': tool,
                        'campaign': campaign,
                    })
    return remaining_runs

def compute_remaining_runs(desired_runs):
    remaining_runs = []
    apis = common.get_apis()
    tools = common.get_tools()
    for api in apis:
        for tool in tools:
            try:
                base_dir = f"{common.RESTGYM_BASE_DIR}/results/{api}/{tool}"
                subdirs = os.listdir(base_dir)
                count = 0
                for subdir in subdirs:
                    if os.path.exists(f"{base_dir}/{subdir}/completed.txt"):
                        count += 1
                while count < desired_runs:
                    remaining_runs.append({'api': api, 'tool': tool, 'campaign': None})
                    count += 1
            except:
                for _ in range(desired_runs):
                    remaining_runs.append({'api': api, 'tool': tool, 'campaign': None})
    return remaining_runs

def check_docker_images(remaining_runs):
    images = set()
    missing_images = []
    for remaining_run in remaining_runs:
        images.add(remaining_run['tool'])
        images.add(remaining_run['api'])
    for image in images:
        try:
            common.DOCKER_CLIENT.images.get(common.DOCKER_PREFIX + image)
        except:
            missing_images.append(image)
    return missing_images

def filter_runs_with_missing_images(remaining_runs, missing_images):
    filtered_remaining_runs = []
    for remaining_run in remaining_runs:
        if remaining_run['tool'] not in missing_images and remaining_run['api'] not in missing_images:
            filtered_remaining_runs.append(remaining_run)
    return filtered_remaining_runs

def remove_excluded_runs(runs, skip_list):
    filtered = []
    for run in runs:
        skip = False
        for s in skip_list:
            if run['api'] == s['api'] and run['tool'] == s['tool']:
                skip = True
                break
        if not skip:
            filtered.append(run)
    return filtered

def check_resources():
    available_ram = getattr(psutil.virtual_memory(), 'available')
    available_cpus = (1 - (psutil.cpu_percent() / 100)) * psutil.cpu_count()
    return available_ram > MINIMUM_RAM_GB * 1024 * 1024 * 1024 and available_cpus > MINIMUM_CPUS

def deep_check_resources():
    for _ in range(10):
        if not check_resources():
            return False
        time.sleep(1)
    return True

def launch_run(api, tool, campaign, run_count, total_runs, progress, experiment_task):
    attempts = 5
    successfully_completed = False
    progress.update(experiment_task, advance=1)

    if campaign is None:
        campaign = {"campaign_id": "no-mutation", "mode": "baseline"}

    campaign_id = campaign.get("campaign_id", "no-mutation")
    base_campaign_id = campaign.get("base_campaign_id", campaign_id)

    while attempts > 0 and not successfully_completed:
        attempts -= 1
        error_occurred = False
        
        # FLAT STRUCTURE: results/api/tool/run
        run = 'run-' + time.strftime('%Y%m%d-%H%M%S')
        results_path = f'{common.RESTGYM_BASE_DIR}/results/{api}/{tool}/{run}'
        
        ports = {'9090/tcp': None}
        env = {
            'API': api, 'TOOL': tool, 'RUN': run,
            'TIME_BUDGET': TIME_BUDGET_MINS, 'HOST': 'localhost',
            'CAMPAIGN_ID': campaign_id,
            'CAMPAIGN_FILE': f'/campaigns/{base_campaign_id}.json',
            'RESULTS_PATH': f'/results/{api}/{tool}/{run}',
        }

        os.makedirs(results_path, exist_ok=True, mode=0o777)
        os.makedirs(f'{results_path}{common.LOGS_PATH}', exist_ok=True, mode=0o777)

        with open(f'{results_path}/campaign.json', 'w') as f:
            json.dump(campaign, f, indent=2)

        message = '[green]START[/green]' if attempts == 4 else '[yellow]RETRY[/yellow]'
        with open(f'{results_path}/time-budget.txt', 'a') as f:
            f.write(f'Time budget: {TIME_BUDGET_MINS} minutes.\nCampaign: {campaign_id}\n')

        print(f" => [{message}] ({run_count}/{total_runs}) Running {tool} on {api} | campaign={campaign_id} ({run}).")
        with open(f'{results_path}/started.txt', 'a') as f:
            f.write(f'Run started on {time.ctime()}.\nCampaign: {campaign_id}\n')

        # FLAT STRUCTURE container names
        api_container_name = f'{common.DOCKER_PREFIX}-{api}-for-{tool}--{run}'
        tool_container_name = f'{common.DOCKER_PREFIX}-{tool}-for-{api}--{run}'

        try:
            common.DOCKER_CLIENT.images.get(common.DOCKER_PREFIX + api)
            common.DOCKER_CLIENT.images.get(common.DOCKER_PREFIX + tool)
        except:
            print(f" => [[red]ERROR[/red]] ({run_count}/{total_runs}) Missing Docker image(s).")
            with open(f'{results_path}/errors.txt', 'a') as f:
                f.write(f"Docker image(s) not found.\n\n")
            error_occurred = True

        api_volumes = [
            f'{common.RESTGYM_BASE_DIR_HOST}/results/:/results/',
            f'{common.RESTGYM_BASE_DIR_HOST}/apis/{api}/campaigns:/campaigns:ro',
            f'{common.RESTGYM_BASE_DIR_HOST}/apis/{api}/specifications/{api}-openapi.json:/specifications/{api}-openapi.json:ro',
        ]

        if not error_occurred:
            try:
                api_container = common.DOCKER_CLIENT.containers.run(
                    image=f'{common.DOCKER_PREFIX}{api}', name=api_container_name,
                    environment=env, ports=ports, volumes=api_volumes,
                    mem_limit='16g', nano_cpus=8_000_000_000,
                    user=f'{os.getuid()}:{os.getgid()}', detach=True
                )
            except Exception as e:
                with open(f'{results_path}/errors.txt', 'a') as f:
                    f.write(f"Could not start API container.\n{e}\n\n")
                error_occurred = True

        if not error_occurred: time.sleep(45)
        else: time.sleep(2)

        if not error_occurred:
            try:
                api_container.reload()
                env['PORT'] = str(int(api_container.attrs['NetworkSettings']['Ports']['9090/tcp'][0]['HostPort']))
            except Exception as e:
                with open(f'{results_path}/errors.txt', 'a') as f:
                    f.write(f"Port 9090 not published.\n{e}\n\n")
                error_occurred = True

        tool_volumes = dict(specification_volumes)
        tool_volumes[f'{common.RESTGYM_BASE_DIR_HOST}/results/'] = {'bind': '/results/', 'mode': 'rw'}

        if not error_occurred:
            try:
                tool_container = common.DOCKER_CLIENT.containers.run(
                    image=f'{common.DOCKER_PREFIX}{tool}', name=tool_container_name,
                    environment=env, privileged=True, volumes=tool_volumes,
                    network_mode='host', mem_limit='16gb', nano_cpus=8_000_000_000, detach=True
                )
                time.sleep(1)
            except Exception as e:
                api_container.stop()
                with open(f'{results_path}/errors.txt', 'a') as f:
                    f.write(f"Could not start tool container.\n{e}\n\n")
                error_occurred = True

        if not error_occurred:
            for minute in range(1, TIME_BUDGET_MINS + 1):
                time.sleep(60)
                progress.update(experiment_task, advance=1)
                try:
                    api_container.reload()
                    if api_container.status == 'exited': raise Exception("API container exited.")
                except Exception as e:
                    with open(f'{results_path}/errors.txt', 'a') as f: f.write(f"API stopped at min {minute}.\n{e}\n\n")
                    try: tool_container.stop()
                    except: pass
                    error_occurred = True
                    break
                try:
                    tool_container.reload()
                    if tool_container.status == 'exited': raise Exception("Tool exited")
                except Exception as e:
                    with open(f'{results_path}/errors.txt', 'a') as f: f.write(f"Tool stopped at min {minute}.\n{e}\n\n")
                    try: api_container.stop()
                    except: pass
                    error_occurred = True
                    break

        if not error_occurred:
            try:
                tool_container.stop()
                tool_container.wait()
            except Exception as e:
                error_occurred = True
                with open(f'{results_path}/errors.txt', 'a') as f: f.write(f'Could not stop tool.\n{e}\n\n')
                try: api_container.stop()
                except: pass

        try:
            with open(f'{results_path}{common.LOGS_PATH}/{tool}-stdout.log', 'wb') as f_out, open(f'{results_path}{common.LOGS_PATH}/{tool}-stderr.log', 'wb') as f_err:
                f_out.write(tool_container.logs(stdout=True, stderr=False))
                f_err.write(tool_container.logs(stdout=False, stderr=True))
            tool_container.remove()
        except Exception as e:
            with open(f'{results_path}/errors.txt', 'a') as f: f.write(f'Could not write log/remove tool.\n{e}\n\n')

        if not error_occurred: time.sleep(5)

        if not error_occurred:
            try:
                api_container.stop()
                api_container.wait()
            except Exception as e:
                error_occurred = True
                with open(f'{results_path}/errors.txt', 'a') as f: f.write(f'Could not stop API.\n{e}\n\n')

        try:
            with open(f'{results_path}{common.LOGS_PATH}/{api}-stdout.log', 'wb') as f_out, open(f'{results_path}{common.LOGS_PATH}/{api}-stderr.log', 'wb') as f_err:
                f_out.write(api_container.logs(stdout=True, stderr=False))
                f_err.write(api_container.logs(stdout=False, stderr=True))
            api_container.remove()
        except Exception as e:
            with open(f'{results_path}/errors.txt', 'a') as f: f.write(f'Could not write log/remove API.\n{e}\n\n')

        if not error_occurred:
            successfully_completed = True
            with open(f'{results_path}/completed.txt', 'a') as f:
                f.write(f'Run completed on {time.ctime()}.\nCampaign: {campaign_id}\n')
            print(f" => [[green]-END-[/green]] ({run_count}/{total_runs}) Run of {tool} on {api} | campaign={campaign_id} ({run}) completed.")
        else:
            time.sleep(2)
            if attempts == 0:
                print(f" => [[red]ERROR[/red]] ({run_count}/{total_runs}) Run of {tool} on {api} | campaign={campaign_id} ({run}) terminated with errors.")

if __name__ == "__main__":
    common.welcome()
    read_config()
    print(f"Time budget: {TIME_BUDGET_MINS} minutes. Minimum CPUs: {MINIMUM_CPUS}. Minimum RAM: {MINIMUM_RAM_GB} GB.")

    if MUTATION_ENABLED:
        print("\n[bold cyan]Mutation testing mode enabled.[/bold cyan]")
        print(f"  Seed: {CAMPAIGN_SEED}")
        print(f"  Budget: {'all' if CAMPAIGN_BUDGET == 0 else CAMPAIGN_BUDGET} campaigns per API/tool")
        print(f"  Repetitions: {CAMPAIGN_REPETITIONS}")

        missing_campaigns = check_campaigns_exist()
        if missing_campaigns:
            print(f"\n[yellow]WARNING[/yellow]: No campaigns found for: {', '.join(missing_campaigns)}")
            answer = input("Continue anyway with available campaigns? [y/N]: ")
            if answer.lower() != 'y': sys.exit(1)

        remaining_runs = compute_remaining_runs_campaign()
        print(f"\nTotal campaign runs planned: {len(remaining_runs)}")
    else:
        print("\n[bold]Standard mode (no mutation).[/bold]")
        try:
            desired_runs = int(input("How many runs? [1-20]: "))
        except:
            print("Please specify a whole number.")
            sys.exit(1)
        if desired_runs < 1 or desired_runs > 20:
            print("Please specify a number in the range 1-20.")
            sys.exit(1)
        remaining_runs = compute_remaining_runs(desired_runs)

    skip_runs = [
        {'api': 'pet-clinic', 'tool': 'schemathesis'}, {'api': 'flight-search', 'tool': 'autoresttest'},
        {'api': 'flight-search', 'tool': 'restest'}, {'api': 'features-service', 'tool': 'evomaster'},
        {'api': 'kafka-rest-proxy', 'tool': 'resttestgen'}, {'api': 'erc20', 'tool': 'cats'},
    ]
    remaining_runs = remove_excluded_runs(remaining_runs, skip_runs)

    missing_images = check_docker_images(remaining_runs)
    if len(missing_images) > 0:
        filtered_remaining_runs = filter_runs_with_missing_images(remaining_runs, missing_images)
        print(f"Missing images. Only {len(filtered_remaining_runs)} out of {len(remaining_runs)} runs can be launched.")
        remaining_runs = filtered_remaining_runs
    else:
        print(f"Runs planned for execution: {len(remaining_runs)}.")

    total_runs = len(remaining_runs)
    run_count = 0

    for api in common.get_apis():
        if common.check_enabled('api', api):
            specification_volumes[f'{common.RESTGYM_BASE_DIR_HOST}/apis/{api}/specifications/{api}-openapi.json'] = {'bind': f'/specifications/{api}-openapi.json', 'mode': 'ro'}
            specification_volumes[f'{common.RESTGYM_BASE_DIR_HOST}/apis/{api}/specifications/{api}.yaml'] = {'bind': f'/specifications/{api}.yaml', 'mode': 'ro'}

    input("Press ENTER to start the execution of the experiment (or CTRL+C to cancel)...")

    with Progress() as progress:
        experiment_task = progress.add_task("Running experiment...", total=total_runs * (TIME_BUDGET_MINS + 1))
        threads = []
        while len(remaining_runs) > 0:
            run_count += 1
            remaining_run = remaining_runs.pop(random.randrange(len(remaining_runs)))
            notify_no_resources = True
            while not deep_check_resources():
                if notify_no_resources:
                    print(f" => [[blue]-WAIT[/blue]] ({run_count}/{total_runs}) Waiting for resources.")
                    notify_no_resources = False
                time.sleep(30)

            run_thread = threading.Thread(
                target=launch_run,
                args=(remaining_run['api'], remaining_run['tool'], remaining_run.get('campaign'), run_count, total_runs, progress, experiment_task),
            )
            run_thread.start()
            threads.append(run_thread)
            if len(remaining_runs) > 0: time.sleep(60)

        for t in threads: t.join()
        print("Execution completed.")