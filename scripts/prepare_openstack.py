import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "data" / "OpenStack_full"
OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "openstack_full.csv"
LABEL_FILE = INPUT_DIR / "anomaly_labels.txt"

INPUT_FILES = [
    INPUT_DIR / "openstack_normal1.log",
    INPUT_DIR / "openstack_normal2.log",
    INPUT_DIR / "openstack_abnormal.log",
]

LOG_PATTERN = re.compile(
    r"^(?P<log_record>\S+)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+"
    r"(?P<pid>\S+)\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<component>\S+)"
    r"(?:\s+(?P<content>.*))?$"
)

UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}\b"
)

REQUEST_PATTERN = re.compile(r"\breq-[0-9a-fA-F-]+\b")
INSTANCE_PATTERN = re.compile(r"\[instance:\s*([0-9a-fA-F-]+)\]")


def read_anomaly_ids():
    ids = set()

    for line in LABEL_FILE.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        value = line.strip()

        if UUID_PATTERN.fullmatch(value):
            ids.add(value.lower())

    return ids


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    anomaly_ids = read_anomaly_ids()

    written = 0
    ignored = 0

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)

        writer.writerow(
            [
                "line_id",
                "event_time",
                "log_record",
                "pid",
                "component",
                "level",
                "correlation_data",
                "request_id",
                "instance_id",
                "content",
                "source_file",
                "scenario",
                "known_anomaly_instance",
                "raw_log",
            ]
        )

        for input_file in INPUT_FILES:
            scenario = (
                "abnormal"
                if input_file.name == "openstack_abnormal.log"
                else "normal"
            )

            with input_file.open(
                "r", encoding="utf-8", errors="replace"
            ) as source:
                for line in source:
                    raw_log = line.rstrip("\r\n")
                    match = LOG_PATTERN.match(raw_log)

                    if not match:
                        ignored += 1

                        if ignored <= 20:
                            print(
                                f"Ignored line in {input_file.name}: "
                                f"{raw_log!r}"
                            )

                        continue

                    fields = match.groupdict()
                    content = fields["content"] or ""
                    correlation_data = ""

                    if content.startswith("[") and "]" in content:
                        closing_bracket = content.find("]")
                        correlation_data = content[1:closing_bracket]
                        content = content[closing_bracket + 1 :].lstrip()

                    request_match = REQUEST_PATTERN.search(raw_log)
                    instance_match = INSTANCE_PATTERN.search(raw_log)

                    request_id = (
                        request_match.group(0) if request_match else ""
                    )
                    instance_id = (
                        instance_match.group(1) if instance_match else ""
                    )

                    known_anomaly_instance = any(
                        anomaly_id in raw_log.lower()
                        for anomaly_id in anomaly_ids
                    )

                    pid = fields["pid"] if fields["pid"].isdigit() else ""

                    written += 1

                    writer.writerow(
                        [
                            written,
                            f'{fields["date"]} {fields["time"].replace(",", ".")}',
                            fields["log_record"],
                            pid,
                            fields["component"],
                            fields["level"],
                            correlation_data,
                            request_id,
                            instance_id,
                            content,
                            input_file.name,
                            scenario,
                            int(known_anomaly_instance),
                            raw_log,
                        ]
                    )

            print(f"Finished {input_file.name}")

    print(f"Finished: {written:,} OpenStack records written")
    print(f"Ignored: {ignored:,} unrecognized lines")
    print(f"Known anomalous instance IDs: {len(anomaly_ids)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
