#!/bin/sh
set -e

# Make directory for results
mkdir -p "/results/$API/$TOOL/$RUN"

# Start MySQL in background
/etc/init.d/mysql start

# Wait until MySQL is ready on TCP
echo "Waiting for MySQL to be ready..."
until mysqladmin ping -h127.0.0.1 --silent; do
  sleep 2
done
echo "MySQL is up."

# Start JaCoCo collector in background
sh /infrastructure/jacoco/collect-coverage-interval.sh &

# sync uv and create venv
cd /infrastructure/mitmproxy/mutations

# Prepare the campaign file argument if it exists
CAMPAIGN_ARG=""
if [ -n "$CAMPAIGN_FILE" ] && [ -f "$CAMPAIGN_FILE" ]; then
  CAMPAIGN_ARG="--set campaign_file=$CAMPAIGN_FILE"
  echo "Running in Campaign Mode: $CAMPAIGN_FILE"
else
  echo "Running in Baseline/Standard Mode (no campaign file found)."
fi

# Start mitmproxy in background
uv run mitmdump -p 9090 --mode reverse:http://127.0.0.1:8080/ \
  -s /infrastructure/mitmproxy/store-interactions/store-interactions.py \
  -s /api/auth.py \
  -s /infrastructure/mitmproxy/mutations/src/mitm_proxy_plugin/addon.py \
  --set openapi_spec=/api/specifications/${API}-openapi.json \
  --set mutation_seed=42 \
  --set exec_log=/results/$API/$TOOL/$RUN/proxy.exec.jsonl \
  $CAMPAIGN_ARG > /results/$API/$TOOL/$RUN/logs/mitmproxy.log 2>&1 &

# Finally start Spring Boot (PID 1 stays java)
exec java \
  -javaagent:/infrastructure/jacoco/org.jacoco.agent-0.8.7-runtime.jar=includes=*,output=tcpserver,port=12345,address=* \
  -Dfile.encoding=UTF-8 \
  -jar /api/blog-sut.jar