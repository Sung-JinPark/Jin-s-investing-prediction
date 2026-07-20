"""dualdb CLI — rebuild / ingest / derive / report / coverage (Makefile 대체, CHANGELOG #2)."""

from __future__ import annotations

import json
import sys

from . import config, db


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    since = None
    if "--since" in args:
        since = args[args.index("--since") + 1]

    conn = db.connect()

    if cmd == "rebuild":
        db.rebuild(conn)
        print("DB 초기화 완료 (원본 data/raw는 보존) — ingest로 재적재")
    elif cmd == "ingest":
        from .ingest import all as ingest_all
        report = ingest_all.run(conn, since)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif cmd == "derive":
        from .derive import daily
        print(json.dumps(daily.run(conn), ensure_ascii=False, indent=2))
    elif cmd == "coverage":
        from .derive import coverage
        print(coverage.report(conn))
    elif cmd == "report":
        from .analysis import weekly
        print(weekly.render(conn))
    elif cmd == "models":
        # P4 모델 4종 실행 (스펙 §8) — 결과는 model_run 기록 + 콘솔 md
        import json as _json
        outs = []
        for name in ("knn_analog", "dtw_daily", "lppl_walkforward", "twins"):
            try:
                if name == "twins":
                    from .analysis import twins as mod
                else:
                    from importlib import import_module
                    mod = import_module(f".models.{name}", "dualdb")
                result = mod.run(conn)
                outs.append(mod.render_md(result))
                print(f"[{name}] 완료")
            except Exception as exc:  # noqa: BLE001 — 모델 1개 실패가 전체를 막지 않게
                outs.append(f"## {name}\n- 실행 실패: {type(exc).__name__}: {exc}\n")
                print(f"[{name}] 실패: {exc}")
        from datetime import datetime as _dt
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = config.REPORTS_DIR / f"models_{_dt.now().strftime('%y%m%d')}.md"
        out_path.write_text("\n\n".join(outs), encoding="utf-8")
        print(f"산출: {out_path}")
    elif cmd == "export":
        from .export import base_rates_auto
        print(f"생성: {base_rates_auto.export(conn)}")
    else:
        print("사용법: python -m dualdb <rebuild|ingest [--since D]|derive|coverage|report>")


if __name__ == "__main__":
    main()
