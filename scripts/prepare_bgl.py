import csv
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = ROOT / "data" / "BGL_full" / "BGL.log"
OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "bgl_full.csv"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    rejected = 0
    empty_content = 0
    null_character_lines = 0

    with INPUT_FILE.open("r", encoding="utf-8", errors="replace") as source:
        with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.writer(destination)

            writer.writerow(
                [
                    "line_id",
                    "event_time",
                    "label",
                    "node",
                    "log_type",
                    "component",
                    "level",
                    "content",
                    "source_file",
                    "is_anomaly",
                    "raw_log",
                ]
            )

            for line_id, line in enumerate(source, start=1):
                raw_log = line.rstrip("\r\n")
                if "\x00" in raw_log:
                    null_character_lines += 1
                    raw_log = raw_log.replace("\x00", "")

                parts = raw_log.split(maxsplit=9)

                if len(parts) == 9:
                    parts.append("")
                    empty_content += 1
                elif len(parts) != 10:
                    rejected += 1
                    continue

                (
                    label,
                    _unix_timestamp,
                    _date,
                    node,
                    time_text,
                    _node_repeat,
                    log_type,
                    component,
                    level,
                    content,
                ) = parts

                try:
                    event_time = datetime.strptime(
                        time_text, "%Y-%m-%d-%H.%M.%S.%f"
                    ).isoformat(sep=" ")
                except ValueError:
                    rejected += 1
                    continue

                writer.writerow(
                    [
                        line_id,
                        event_time,
                        label,
                        node,
                        log_type,
                        component,
                        level,
                        content,
                        INPUT_FILE.name,
                        0 if label == "-" else 1,
                        raw_log,
                    ]
                )

                written += 1

                if written % 500_000 == 0:
                    print(f"Processed {written:,} BGL records")

    print(f"Finished: {written:,} records written")
    print(f"Rejected: {rejected:,} lines")
    print(f"Empty content records preserved: {empty_content:,}")
    print(f"Null-character lines cleaned: {null_character_lines:,}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
