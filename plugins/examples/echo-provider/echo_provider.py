import json
import sys


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        last = request.get("messages", [{}])[-1].get("content", "")
        print(json.dumps({"type": "token", "text": f"Echo: {last}"}, ensure_ascii=False), flush=True)
        print(json.dumps({"type": "done"}), flush=True)


if __name__ == "__main__":
    main()
