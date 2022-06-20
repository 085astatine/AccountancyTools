#!/usr/bin/env python

from __future__ import annotations
import argparse
import contextlib
import dataclasses
import datetime
import logging
import pathlib
import re
import sys
from typing import Iterator, Optional, TextIO


def main() -> None:
    # logger
    logger = create_logger()
    # option
    option = argument_parser().parse_args()
    if option.verbose:
        logger.setLevel(logging.DEBUG)
    logger.debug(f'option: {option}')
    # receipts
    receipts: list[Receipt] = []
    for markdown in [MarkdownFile(target) for target in option.targets]:
        receipts.extend(markdown.receipts(logger=logger))
    # output
    output_as_csv(receipts, path=option.output)


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

    def receipts(
            self,
            *,
            logger: logging.Logger) -> list[Receipt]:
        logger = logger or logging.getLogger(__name__)
        # open
        logger.debug(f'open: {self.path.as_posix()}')
        with self.path.open(encoding='utf-8') as file:
            text = file.read()
        # parse text
        receipts: list[Receipt] = []
        for data in re.finditer(
                r'^\|(?P<day>\d+)'
                r'\|(?P<hour>\d{2}):(?P<minute>\d{2})'
                r'\|(?P<store>[^\|]+)'
                r'\|(.*\|){2}\n'
                r'(^\|{4}(.*\|){2}\n)*?'
                r'(?=!)',
                text,
                flags=re.MULTILINE):
            logger.debug(f'receipt text: {repr(data.group())}')
            # parse receipt items
            items: list[ReceiptItem] = []
            for row in data.group().strip().split('\n'):
                columns = row.split('|')
                items.append(ReceiptItem(
                        name=columns[4],
                        price=int(columns[5])))
            # receipt
            receipt = Receipt(
                    year=self.year,
                    month=self.month,
                    day=int(data.group('day')),
                    hour=int(data.group('hour')),
                    minute=int(data.group('minute')),
                    store=data.group('store'),
                    items=items)
            logger.info(f'receipt: {receipt}')
            receipts.append(receipt)
        return receipts

    def _validate(self) -> None:
        # check if the path exists
        if not self.path.exists():
            raise InvalidMarkdownFileError(
                    f'"{self.path.as_posix()}" does not exist')
        # check if the path is file
        if not self.path.is_file():
            raise InvalidMarkdownFileError(
                    f'{self.path.as_posix()} is not file')
        # match YYYY/MM.md
        filename_match = re.search(
                r'/\d{4}/(0[1-9]|1[0-2])\.md$',
                self.path.as_posix())
        if filename_match is None:
            raise InvalidMarkdownFileError(
                    f'"{self.path.as_posix()}" is not YYYY/MM.md')


@dataclasses.dataclass
class ReceiptItem:
    name: str
    price: int


@dataclasses.dataclass
class Receipt:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    store: str
    items: list[ReceiptItem]

    @property
    def datetime(self) -> datetime.datetime:
        return datetime.datetime(
                year=self.year,
                month=self.month,
                day=self.day,
                hour=self.hour,
                minute=self.minute)

    def total_price(self) -> int:
        return sum(item.price for item in self.items)


def output_as_csv(
        receipts: list[Receipt],
        *,
        path: Optional[pathlib.Path] = None) -> None:
    records: list[str] = []
    last_number: Optional[str] = None
    for receipt in receipts:
        # date
        date = receipt.datetime.strftime('%Y-%m-%d')
        # number
        number = receipt.datetime.strftime('%Y%m%d%H%M')
        if last_number is not None and last_number.startswith(number):
            number = f'{last_number}#'
        last_number = number
        # total place
        total_price = receipt.total_price()
        # date, number, description, account, value
        records.extend([
                f'{date},{number},{receipt.store},item,{total_price}',
                f',,,payment,{-total_price}'])
    with open_output(path) as output:
        for record in records:
            output.write(f'{record}\n')


def create_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.WARNING)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.formatter = logging.Formatter(
                fmt='%(name)s:%(levelname)s:%(message)s')
        logger.addHandler(handler)
    return logger


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    # targets
    parser.add_argument(
            'targets',
            nargs='*',
            metavar='YYYY/MM.md',
            type=pathlib.Path,
            help='target markdown')
    # verbose
    parser.add_argument(
            '-v', '--verbose',
            action='store_true',
            help='set log level to debug')
    # output
    parser.add_argument(
            '-o', '--output',
            type=pathlib.Path,
            help='output file (default stdout)')
    return parser


@contextlib.contextmanager
def open_output(
        path: Optional[pathlib.Path] = None) -> Iterator[TextIO]:
    output = (
            path.open(mode='w', encoding='utf-8')
            if path is not None
            else sys.stdout)
    try:
        yield output
    finally:
        if path is not None:
            output.close()


if __name__ == '__main__':
    main()
