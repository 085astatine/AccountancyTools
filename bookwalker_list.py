#!/usr/bin/env python

from __future__ import annotations
import argparse
import contextlib
import dataclasses
import datetime
import logging
import pathlib
import sys
from typing import Iterator, Optional, TextIO
import accountancy


def main() -> None:
    # logger
    logger = create_logger()
    # option
    option = argument_parser().parse_args()
    if option.verbose:
        logger.setLevel(logging.DEBUG)
    # load reports
    reports = accountancy.find_monthly_reports(
            option.target,
            logger=logger)
    # receipts
    receipts: list[accountancy.Receipt] = []
    for report in reports:
        receipts.extend(report.payment(logger=logger))
    # books
    books: list[Book] = []
    for receipt in receipts:
        # filter by store
        if receipt.store != 'BOOK☆WALKER':
            continue
        # items
        for item in receipt.items:
            # filter by item name
            if not is_book(item):
                continue
            books.append(Book(
                    title=item.name,
                    price=item.price,
                    purchase_time=receipt.datetime,
                    line_number=item.line_number))
    # sort by title
    books.sort()
    # output
    with open_output(option.output) as output:
        for book in books:
            purchase_date = book.purchase_time.strftime('%Y/%m/%d')
            output.write(
                    f'{book.title}\t'
                    f'{purchase_date}\t'
                    f'{book.line_number}\n')


@dataclasses.dataclass(frozen=True, order=True)
class Book:
    title: str
    price: int
    purchase_time: datetime.datetime
    line_number: int


def is_book(item: accountancy.ReceiptItem) -> bool:
    return (item.name != 'コイン利用'
            and item.name != '消費税'
            and item.name != 'クーポン割引'
            and not item.name.startswith('期間限定コイン')
            and not item.name.startswith('BOOK☆WALKER コイン'))


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
    # target
    parser.add_argument(
            '--target',
            metavar='DIR',
            type=pathlib.Path,
            default=pathlib.Path(),
            help='target directory')
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
