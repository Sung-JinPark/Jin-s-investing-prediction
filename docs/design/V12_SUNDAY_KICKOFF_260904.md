# 킥오프 프롬프트 — 일요일 Opus 루프 배치·스모크·기동 세션용 (금·토 아무 때나 1회 실행, 이후 무개입)

```
NASDAQ_V12_SUNDAY_OPUS_LOOP_PACK_20260904.zip 을 전달한다. C:/workspace/ai-investing 에서 순서대로:

1. [배치] 브랜치 claude/v12-sunday 신설(main 금지). 설계도 → docs/design/, ralph/ 3개 파일 →
   data/timeseries_v12/ralph/, sunday_opus_loop.sh → tools/. LF 정규화(sed 's/\r$//') + bash -n.
2. [전제 확인] claude CLI 존재·--model opus 호출 1회 테스트("say ok"). .venv scipy/numpy import.
   V8/V2 봉인 해시가 e3ff2fdb… 로 시작함을 확인하고 기록. data/runs·ledgers 읽기 가능 확인.
3. [스모크] DRY_RUN=1 bash tools/sunday_opus_loop.sh → 로그에 BOOT·baseline·13태스크 순서 확인 후
   backlog status를 전부 '대기'로 되돌린다(DRY_RUN이 완료로 표기함). 그 다음 MAX_ITER=1 실제 1회
   (S1-1, Opus 호출)로 result JSON·RESULT 라인 파싱·로컬 커밋이 동작하는지 확인. 통과 시 S1-1은 완료 유지.
4. [기동 — 스모크 통과 즉시, 사용자 개입 없음] 절전 해제(powercfg /change standby-timeout-ac 0) 확인 후 바로 실행.
   스크립트가 LOOP_START_EPOCH(일 09:00 KST)까지 스스로 대기했다가 자동 시작한다:
   nohup env LOOP_START_EPOCH=1788652800 LOOP_DEADLINE_EPOCH=1788739200 MONDAY_CKPT_EPOCH=1788706800 LOOP_MODEL=opus \
     bash tools/sunday_opus_loop.sh >> outputs/timeseries_v12/loop/nohup.out 2>&1 &
   중단은 touch outputs/timeseries_v12/loop/ABORT, 재개는 같은 명령(backlog 상태 기반 멱등).
5. [절대 규율] 백테스트·홀드아웃·봉인·refresh 0회 · 봉인 0바이트 · 원장 무수정 · main/push 금지 ·
   시크릿 미로드. 루프 밖의 어떤 실험도 이 세션에서 하지 마라.
6. [월요일] 09:00 자동 정지 후 docs/review/SUNDAY_LOOP_FINAL_REPORT.md 와 V12-D1~D4 결정표를 확인해
   보고하라. push/PR은 사용자 승인 후.
```
