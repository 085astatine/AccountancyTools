#!/usr/bin/env python

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import logging
import pathlib
import re
import sys
from typing import Iterator, Optional, TextIO

from accountancy import Payment, PaymentItem, PaymentKey


def main() -> None:
    # logger
    logger = create_logger()
    # option
    option = argument_parser().parse_args()
    if option.verbose:
        logger.setLevel(logging.DEBUG)
    logger.debug("option: %s", option)
    # payments
    payments: list[Payment] = []
    for markdown in [MarkdownFile(target) for target in option.targets]:
        payments.extend(markdown.payments(logger=logger))
    # output
    output_as_csv(payments, path=option.output)


class InvalidMarkdownFileError(Exception):
    pass


@dataclasses.dataclass
class MarkdownFile:
    path: pathlib.Path

    def __post_init__(self) -> None:
        # resolve
        self.path = self.path.resolve()
        # validation
        self._validate()

    @property
    def month(self) -> int:
        return int(self.path.stem)

    @property
    def year(self) -> int:
        return int(self.path.parent.name)

    def payments(
        self,
        *,
        logger: logging.Logger,
    ) -> list[Payment]:
        logger = logger or logging.getLogger(__name__)
        # open
        logger.debug("open: %s", self.path.as_posix())
        text = self.path.read_text(encoding="utf-8")
        # parse text
        payments: list[Payment] = []
        for data in re.finditer(
            rf"^\|{PaymentKey.pattern(date_format='D')}\|(.*\|){{2}}\n"
            r"(^\|{4}(.*\|){2}\n)*?"
            r"!(?P<total_price>\d+)",
            text,
            flags=re.MULTILINE,
        ):
            logger.debug("payment text: %s", repr(data.group()))
            total_price = int(data.group("total_price"))
            # parse payment items
            items: list[PaymentItem] = []
            table = re.sub(r"\n!\d+$", "", data.group()).strip()
            for row in table.split("\n"):
                columns = row.split("|")
                items.append(
                    PaymentItem(
                        name=columns[4],
                        price=int(columns[5]),
                    ),
                )
            # payment
            payment = Payment(
                key=PaymentKey(
                    year=self.year,
                    month=self.month,
                    day=int(data.group("day")),
                    hour=int(data.group("hour")),
                    minute=int(data.group("minute")),
                    store=data.group("store"),
                ),
                items=items,
            )
            logger.info("payment: %s", payment)
            if payment.total_price() != total_price:
                logger.error(
                    "mismatch total price: %s at %s",
                    payment.key.store,
                    payment.key.datetime(),
                )
            payments.append(payment)
        return payments

    def _validate(self) -> None:
        # check if the path exists
        if not self.path.exists():
            raise InvalidMarkdownFileError(f'"{self.path.as_posix()}" does not exist')
        # check if the path is file
        if not self.path.is_file():
            raise InvalidMarkdownFileError(f"{self.path.as_posix()} is not file")
        # match YYYY/MM.md
        filename_match = re.search(
            r"/\d{4}/(0[1-9]|1[0-2])\.md$",
            self.path.as_posix(),
        )
        if filename_match is None:
            raise InvalidMarkdownFileError(
                f'"{self.path.as_posix()}" is not YYYY/MM.md'
            )


def output_as_csv(
    payments: list[Payment],
    *,
    path: Optional[pathlib.Path] = None,
) -> None:
    records: list[str] = []
    last_number: Optional[str] = None
    for payment in payments:
        # date
        date = payment.key.datetime().strftime("%Y-%m-%d")
        # number
        number = payment.key.datetime().strftime("%Y%m%d%H%M")
        if last_number is not None and last_number.startswith(number):
            number = f"{last_number}#"
        last_number = number
        # total place
        total_price = payment.total_price()
        # date, number, description, account, value
        records.extend(
            [
                f"{date},{number},{payment.key.store},item,{total_price}",
                f",,,payment,{-total_price}",
            ]
        )
    with open_output(path) as output:
        for record in records:
            output.write(f"{record}\n")


def create_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.WARNING)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.formatter = logging.Formatter(
            fmt="%(name)s:%(levelname)s:%(message)s",
        )
        logger.addHandler(handler)
    return logger


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    # targets
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="YYYY/MM.md",
        type=pathlib.Path,
        help="target markdown",
    )
    # verbose
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="set log level to debug",
    )
    # output
    parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        help="output file (default stdout)",
    )
    return parser


@contextlib.contextmanager
def open_output(
    path: Optional[pathlib.Path] = None,
) -> Iterator[TextIO]:
    try:
        if path is None:
            yield sys.stdout
        else:
            with path.open(mode="w", encoding="utf-8") as output:
                yield output
    finally:
        pass


if __name__ == "__main__":
    main()
