#!/bin/bash
# systemd ExecStartPre script — 清掉上次 crash 殘留的 multiprocessing 子進程。
#
# 為什麼要獨立 script，不直接寫 inline 在 ExecStartPre：
# 若寫成 ExecStartPre=/bin/sh -c 'pkill -9 -f multiprocessing.spawn ...'，
# 那個 sh 進程的 cmdline 會「包含」字串 "multiprocessing.spawn"。pkill -f
# scan 所有 process 的 cmdline 找 match，sh 自己就符合 → pkill 把 parent
# shell 一起 SIGKILL → ExecStartPre 失敗 → service 起不來。pkill 自己有
# self-protect（不會殺自己），但 sh 沒有。
#
# 抽成 script 後，bash 跑這個檔的 cmdline 是
#   /bin/bash /opt/transcriber/deploy/pre-start-cleanup.sh
# 不含 pattern → 不會自殺。
set +e
pkill -9 -f multiprocessing.spawn
pkill -9 -f multiprocessing.resource_tracker
exit 0
