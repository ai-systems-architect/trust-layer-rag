import time
import boto3
import logging
from config import AWS_REGION, DB_IDENTIFIER

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


POLL_INTERVAL = 15  # seconds between status checks
TIMEOUT = 600       # 10 minutes max wait


def start_rds() -> str:
    """Start RDS instance and wait until available. Returns endpoint."""
    client = boto3.client("rds", region_name=AWS_REGION)

    # check current state before issuing start
    response = client.describe_db_instances(DBInstanceIdentifier=DB_IDENTIFIER)
    instance = response["DBInstances"][0]
    status = instance["DBInstanceStatus"]

    if status == "available":
        endpoint = instance["Endpoint"]["Address"]
        logger.info("Already running — %s", endpoint)
        return endpoint

    if status != "stopped":
        raise RuntimeError(f"Cannot start — instance is in state: {status}")

    logger.info("Starting RDS instance: %s", DB_IDENTIFIER)
    client.start_db_instance(DBInstanceIdentifier=DB_IDENTIFIER)

    # poll until available
    elapsed = 0
    while elapsed < TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        response = client.describe_db_instances(DBInstanceIdentifier=DB_IDENTIFIER)
        instance = response["DBInstances"][0]
        status = instance["DBInstanceStatus"]
        logger.info("Status: %s (%ds elapsed)", status, elapsed)

        if status == "available":
            endpoint = instance["Endpoint"]["Address"]
            logger.info("RDS available — endpoint: %s", endpoint)
            logger.info("Update .env: RDS_ENDPOINT=%s", endpoint)
            return endpoint

    raise TimeoutError(f"RDS did not become available within {TIMEOUT}s")


if __name__ == "__main__":
    start_rds()
