import time
import boto3
import logging
from config import AWS_REGION, DB_IDENTIFIER

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

POLL_INTERVAL = 15  # seconds between status checks
TIMEOUT = 600       # 10 minutes max wait


def stop_rds() -> None:
    """Stop RDS instance and wait until stopped. Billing pauses when stopped."""
    client = boto3.client("rds", region_name=AWS_REGION)

    # check current state before issuing stop
    response = client.describe_db_instances(DBInstanceIdentifier=DB_IDENTIFIER)
    instance = response["DBInstances"][0]
    status = instance["DBInstanceStatus"]

    if status == "stopped":
        logger.info("Already stopped — no action needed")
        return

    if status != "available":
        raise RuntimeError(f"Cannot stop — instance is in state: {status}")

    logger.info("Stopping RDS instance: %s", DB_IDENTIFIER)
    client.stop_db_instance(DBInstanceIdentifier=DB_IDENTIFIER)

    # poll until stopped
    elapsed = 0
    while elapsed < TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        response = client.describe_db_instances(DBInstanceIdentifier=DB_IDENTIFIER)
        status = response["DBInstances"][0]["DBInstanceStatus"]
        logger.info("Status: %s (%ds elapsed)", status, elapsed)

        if status == "stopped":
            logger.info("RDS stopped — billing paused")
            return

    raise TimeoutError(f"RDS did not stop within {TIMEOUT}s")


if __name__ == "__main__":
    stop_rds()
