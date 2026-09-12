import asyncio
import argparse
from dummy_sensor_source import DummySensorNode
from synchroniser import Synchroniser
from mqtt_client import MQTTClientWrapper
from logger_setup import get_logger
from constants import PORT_TLS, TRANSPORT_TLS, TOPIC_SENSOR, CA_CERTS_PATH


async def publisher_task(output_queue: asyncio.Queue, mqtt_client: MQTTClientWrapper, logger):
    while True:
        paired_sample = await output_queue.get()
        mqtt_client.publish(TOPIC_SENSOR, paired_sample, qos=0)
        logger.debug(f"Published synchronised sample ts={paired_sample['timestamp']}")


async def main(verbose: bool):
    logger = get_logger("laptop", verbose=verbose)

    forearm_queue = asyncio.Queue()
    paddle_queue = asyncio.Queue()
    output_queue = asyncio.Queue()

    forearm_node = DummySensorNode("forearm", forearm_queue, logger)
    paddle_node = DummySensorNode("paddle", paddle_queue, logger)
    sync = Synchroniser(forearm_queue, paddle_queue, output_queue, logger)

    mqtt_client = MQTTClientWrapper(
        client_id="laptop_gateway",
        port=PORT_TLS,
        transport=TRANSPORT_TLS,
        ca_certs=CA_CERTS_PATH,
        logger=logger,
    )
    mqtt_client.loop_start()  # runs on its own background thread

    await asyncio.gather(
        forearm_node.run(),
        paddle_node.run(),
        sync.run(),
        publisher_task(output_queue, mqtt_client, logger),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.verbose))
    except KeyboardInterrupt:
        print("\nShutting down...")