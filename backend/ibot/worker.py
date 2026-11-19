import time

from ibot.db import connect
from ibot.engine import claim_next_run, execute_run, resume_interrupted


def main():
    db = connect()
    resume_interrupted(db)
    while True:
        run_id = claim_next_run(db)
        if not run_id:
            time.sleep(0.4)
            continue
        try:
            execute_run(db, run_id)
        except Exception as error:
            print(error, flush=True)


if __name__ == '__main__':
    main()
