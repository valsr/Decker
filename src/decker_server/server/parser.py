import argparse


def create_parser():
    parser = argparse.ArgumentParser(description="Decker server")
    parser.add_argument(
        "device",
        type=str,
        help="Device ID to start server for",
    )
