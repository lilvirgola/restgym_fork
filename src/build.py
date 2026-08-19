import common
import os
import sys
import math
import json
import subprocess
import multiprocessing
import concurrent.futures
from rich import print


# ---------------------------------------------------------------------------
# Docker image management (original)
# ---------------------------------------------------------------------------
def clean_builds():
    print("Removing old images...")
    images = common.get_apis() + common.get_tools()
    for image in images:
        print(f" => {image}: ", end='')
        try:
            common.DOCKER_CLIENT.images.remove(image=common.DOCKER_PREFIX + image)
            print("Removed.")
        except:
            print("Image not found. Skipping.")


def build(image):
    try:
        common.DOCKER_CLIENT.images.get(common.DOCKER_PREFIX + image)
        print(f" => {image}: Already available in the local image registry.")
    except:
        sub_path = 'tools' if image in common.get_tools() else 'apis'
        path = f"{common.RESTGYM_BASE_DIR}/{sub_path}/{image}"
        print(f" => {image}: Building...")
        if os.path.exists(f"{path}/Dockerfile"):
            try:
                common.DOCKER_CLIENT.images.build(
                    path=f'{common.RESTGYM_BASE_DIR}',
                    dockerfile=f'{path}/Dockerfile',
                    tag=common.DOCKER_PREFIX + image,
                    rm=True,
                    forcerm=True
                )
                print(f" => {image}: Done.")
            except Exception as e:
                print(f" => {image}: An error occurred during the build. Skipping.")
                print(f" => {image}: {e}")
        else:
            print(f" => {image}: Dockerfile not found. Skipping.")


def build_all():
    print("Building images...")
    images = common.get_apis() + common.get_tools()

    threads = math.floor(multiprocessing.cpu_count() * 0.9)

    with concurrent.futures.ThreadPoolExecutor(threads) as executor:
        for image in images:
            build(image)


# ---------------------------------------------------------------------------
# CAMPAIGN: generate mutation campaigns for all APIs
# ---------------------------------------------------------------------------
def generate_campaigns_for_all_apis(seed=42, disabled_operators="", force=False):
    """
    Generate mutation campaigns for every enabled API by calling
    the plugin's generate_campaigns.py script via subprocess.
    """

    mutations_dir = os.path.join(
        common.RESTGYM_BASE_DIR,
        "infrastructure", "mitmproxy", "mutations"
    )

    script_path = os.path.join(mutations_dir, "scripts", "generate_campaigns.py")

    if not os.path.exists(script_path):
        print(f"[red]ERROR[/red]: Campaign generation script not found at:")
        print(f"  {script_path}")
        print("Make sure the mitmproxy mutation plugin is installed.")
        return False

    print("\n[cyan]Generating mutation campaigns...[/cyan]")
    print(f"  Seed: {seed}")
    print(f"  Disabled operators: {disabled_operators or 'none'}")
    print(f"  Force: {force}")
    print()

    success_count = 0
    skip_count = 0
    error_count = 0

    for api in common.get_apis():
        if not common.check_enabled('api', api):
            continue

        spec_path = os.path.join(
            common.RESTGYM_BASE_DIR,
            "apis", api, "specifications", f"{api}-openapi.json"
        )
        campaigns_dir = os.path.join(
            common.RESTGYM_BASE_DIR,
            "apis", api, "campaigns"
        )
        manifest_path = os.path.join(campaigns_dir, "manifest.jsonl")

        # Skip if campaigns already exist and not forcing
        if os.path.exists(manifest_path) and not force:
            with open(manifest_path, "r") as f:
                count = sum(1 for line in f if line.strip())
            print(f"  [green]OK[/green]   {api}: {count} campaigns already exist. Use force to regenerate.")
            skip_count += 1
            continue

        if not os.path.exists(spec_path):
            print(f"  [yellow]SKIP[/yellow] {api}: spec not found.")
            skip_count += 1
            continue

        print(f"  [cyan]GEN[/cyan]  {api}: generating...", end='', flush=True)

        # Build the command
        cmd = [
            "uv", "run", "python", script_path,
            "--spec", spec_path,
            "--seed", str(seed),
            "--out-dir", campaigns_dir,
        ]

        if disabled_operators:
            cmd.extend(["--disabled-operators", disabled_operators])

        try:
            result = subprocess.run(
                cmd,
                cwd=mutations_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                # Count generated campaigns
                if os.path.exists(manifest_path):
                    with open(manifest_path, "r") as f:
                        count = sum(1 for line in f if line.strip())
                    print(f" {count} campaigns.")
                else:
                    print(" done.")
                success_count += 1
            else:
                print(f" [red]FAILED[/red]")
                print(f"         stderr: {result.stderr.strip()[:200]}")
                error_count += 1

        except subprocess.TimeoutExpired:
            print(f" [red]TIMEOUT[/red]")
            error_count += 1
        except FileNotFoundError:
            print(f" [red]ERROR[/red]: 'uv' not found. Install uv first.")
            return False
        except Exception as e:
            print(f" [red]ERROR[/red]: {e}")
            error_count += 1

    print()
    print(f"  Campaign generation complete: "
          f"{success_count} generated, {skip_count} skipped, {error_count} errors.")

    return error_count == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    common.welcome()
    print("This is the build module.")
    print()
    print("[1] Clean and build images")
    print("[2] Build images")
    print("[3] Clean images")
    print("[4] Generate mutation campaigns")
    print("[5] Build images + generate campaigns")
    print()

    choice = input("Your choice: ")

    if choice not in ('1', '2', '3', '4', '5'):
        print("Invalid choice!")
        sys.exit(1)

    # Clean
    if choice in ('1', '3'):
        clean_builds()

    # Build
    if choice in ('1', '2', '5'):
        build_all()

    # Generate campaigns
    if choice in ('4', '5'):
        print()
        try:
            seed = int(input("Campaign seed [42]: ") or "42")
        except ValueError:
            seed = 42

        disabled = input(
            "Disabled operators (comma-separated) "
            "[Timeout,ConnectionDrop,TimeoutThenDrop,TooMuchData]: "
        ).strip()
        if not disabled:
            disabled = "Timeout,ConnectionDrop,TimeoutThenDrop,TooMuchData"

        force_input = input("Force regeneration? [y/N]: ").strip().lower()
        force = force_input == 'y'

        generate_campaigns_for_all_apis(
            seed=seed,
            disabled_operators=disabled,
            force=force,
        )

    print("\nCompleted.")