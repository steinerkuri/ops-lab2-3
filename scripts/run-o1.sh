#!/usr/bin/env bash
# 先在 LAB2.md 记录预测；启动 GOGC=100 或 400 的新 enrolld 后各运行一次。
# 示例：GEN_CPUS=0-1 scripts/run-o1.sh o1-gogc100 100
set -euo pipefail
name=${1:?用法：run-o1.sh 名字 GOGC值}
gogc=${2:?缺少 GOGC值}
[[ $name =~ ^[A-Za-z0-9._-]+$ ]] || exit 1
[[ $gogc == 100 || $gogc == 400 ]] || exit 1
[[ ! -e runs/$name && ! -e runs/$name-warmup ]] || { echo '结果目录已存在'; exit 1; }
svc=${SVC:-http://127.0.0.1:8080}
config=$(curl -fsS "$svc/config")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["gogc"] == sys.argv[2], "服务 GOGC 与参数不符"' "$config" "$gogc"
mkdir -p "runs/$name-warmup"
printf '%s\n' "$config" > "runs/$name-warmup/config.json"
taskset -c "${GEN_CPUS:-0-1}" bin/loadgen -url "$svc/api/report?mb=4" -rates 100 -step 30s -out "runs/$name-warmup/steps.csv" > "runs/$name-warmup/loadgen.log" 2>&1
GEN_CPUS=${GEN_CPUS:-0-1} scripts/run.sh "$name" -url "$svc/api/report?mb=4" -rates 100 -step 60s
bin/promsteps -steps "runs/$name/steps.csv" -prom "${PROM:-http://127.0.0.1:9090}" -queries deploy/queries-o1.txt > "runs/$name/gc.csv"
