#!/usr/bin/env bash
#
# fast_nfs_copy.sh — 并行拷贝大量 jsonl 文件到 NFS 挂载盘
#
# 用法:
#   1. 修改下面 SRC / DST 两个变量（或用环境变量覆盖）
#   2. bash fast_nfs_copy.sh
#
# 环境变量覆盖示例:
#   SRC=/data/jsonl DST=/nfs/backup JOBS=16 bash fast_nfs_copy.sh

# ========== 手动配置区 ==========
SRC="${SRC:-/path/to/source/dir}"          # 原文件夹
DST="${DST:-/mnt/nfs/target/dir}"          # 目标文件夹（NFS 挂载点）
JOBS="${JOBS:-16}"                         # 并行数，建议 8~32，NFS 一般 16 起步
LOG="${LOG:-copy_$(date +%Y%m%d_%H%M%S).log}"
# =================================

set -u

command -v rsync >/dev/null 2>&1 || { echo "需要安装 rsync"; exit 1; }

[ -d "$SRC" ] || { echo "源目录不存在: $SRC"; exit 1; }
mkdir -p "$DST" || { echo "无法创建目标目录: $DST"; exit 1; }

SRC_ABS=$(cd "$SRC" && pwd)
DST_ABS=$(cd "$DST" && pwd)

echo "源:   $SRC_ABS"
echo "目标: $DST_ABS"
echo "并行: $JOBS"
echo "日志: $LOG"
echo

# 先在源端同步目录结构（串行、很快）
cd "$SRC_ABS"
find . -type d ! -path '.' -print0 | xargs -0 -I{} mkdir -p "$DST_ABS/{}"

# 生成文件列表：按文件大小降序（大文件先拷，避免结尾“长尾”）
FILE_LIST=$(mktemp)
find . -type f -printf '%s %p\n' | sort -rn | cut -d' ' -f2- > "$FILE_LIST"

TOTAL_FILES=$(wc -l < "$FILE_LIST")
TOTAL_SIZE=$(du -sb "$SRC_ABS" | cut -f1)
echo "共 $TOTAL_FILES 个文件, 总计 $(numfmt --to=iec $TOTAL_SIZE)"
echo

START=$(date +%s)
DONE=0
FAIL=0
FAIL_LIST=$(mktemp)

copy_one() {
    local f="$1"
    local src="$SRC_ABS/$f"
    local dst="$DST_ABS/$f"

    # 跳过已完成（大小一致）的文件 —— 支持中断后续跑
    local ssz dsz
    ssz=$(stat -c%s "$src" 2>/dev/null) || return 1
    dsz=$(stat -c%s "$dst" 2>/dev/null) || dsz=-1
    if [ "$ssz" = "$dsz" ]; then
        echo "SKIP  $f"
        return 0
    fi

    # whole-file: 本地→NFS 无需增量算法；no-compression: 数据已在网盘上更省 CPU
    if rsync -a --whole-file --inplace --no-compress \
             --info=NAME0,STATS0 "$src" "$dst" 2>>"$LOG.err"; then
        # 拷完校验大小
        local nsz
        nsz=$(stat -c%s "$dst" 2>/dev/null) || nsz=-1
        if [ "$ssz" = "$nsz" ]; then
            echo "OK    $f"
            return 0
        fi
    fi
    echo "FAIL  $f" >&2
    return 1
}
export -f copy_one
export SRC_ABS DST_ABS LOG

# 进度上报：每完成 N 个文件刷一行统计
report() {
    local elapsed=$(( $(date +%s) - START ))
    local pct=$(( DONE * 100 / (TOTAL_FILES + 1) ))
    printf "\r进度: %d/%d (%d%%)  失败:%d  用时:%02d:%02d:%02d" \
        "$DONE" "$TOTAL_FILES" "$pct" "$FAIL" \
        $((elapsed/3600)) $((elapsed%3600/60)) $((elapsed%60))
}

# 用 xargs 控制并行（比 GNU parallel 依赖少）
while IFS= read -r f; do
    # 控制并发：挂起的任务数达到 JOBS 就等一个
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do
        wait -n
    done
    (
        if copy_one "$f"; then
            :
        else
            echo "$f" >> "$FAIL_LIST"
        fi
    ) &
    DONE=$((DONE + 1))
    [ $((DONE % 20)) -eq 0 ] && report
done < "$FILE_LIST"

wait
echo
echo "========================================"
ELAPSED=$(( $(date +%s) - START ))
FAIL=$(wc -l < "$FAIL_LIST" | tr -d ' ')

echo "完成: $((TOTAL_FILES - FAIL))/$TOTAL_FILES 个文件"
echo "总用时: $((ELAPSED/60)) 分 $((ELAPSED%60)) 秒"
echo "平均速度: $(numfmt --to=iec $(( TOTAL_SIZE / (ELAPSED+1) )) )/s"

if [ "$FAIL" -gt 0 ]; then
    echo
    echo "以下 $FAIL 个文件失败，已记录到 $FAIL_LIST，可重跑本脚本自动重试:"
    head -20 "$FAIL_LIST"
    rm -f "$FILE_LIST"
    exit 1
fi

rm -f "$FILE_LIST" "$FAIL_LIST"
echo "全部拷贝完成 ✔"
