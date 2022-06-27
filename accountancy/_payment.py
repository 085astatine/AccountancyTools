from __future__ import annotations
import dataclasses
import datetime
import logging
import re
from typing import TYPE_CHECKING, Final, Generator, Literal, Optional
if TYPE_CHECKING:
    from ._monthly_report import MonthlyReportLine


@dataclasses.dataclass(frozen=True)
class ReceiptItem:
    name: str
    price: int
    line_number: int


@dataclasses.dataclass(frozen=True)
class Receipt:
    # pylint: disable=too-many-instance-attributes
    year: int
    month: int
    day: int
    hour: int
    minute: int
    store: str
    items: list[ReceiptItem]
    line_number: int

    @property
    def datetime(self) -> datetime.datetime:
        return datetime.datetime(
                year=self.year,
                month=self.month,
                day=self.day,
                hour=self.hour,
                minute=self.minute)

    @property
    def last_line_number(self) -> int:
        return self.line_number + len(self.items) - 1

    def to_table_rows(self) -> list[str]:
        rows: list[str] = []
        for item in self.items:
            if rows:
                rows.append(f'||||{item.name}|{item.price}|')
            else:
                rows.append(
                        f'|{self.day}'
                        f'|{self.hour:02}:{self.minute:02}'
                        f'|{self.store}'
                        f'|{item.name}|{item.price}|')
        return rows

    def to_table(self) -> str:
        return '\n'.join(self.to_table_rows())


def parse_payment(
        year: int,
        month: int,
        lines: list[MonthlyReportLine],
        *,
        logger: Optional[logging.Logger]) -> list[Receipt]:
    logger = logger or logging.getLogger(__name__)

    receipts: list[Receipt] = []
    tables = _parse_payment_table(lines, logger)
    for table in tables:
        parser = _PaymentTableParser(year, month, logger)
        for row in table:
            parser.push(row)
        receipts.extend(parser.result())
    # sort by old...new
    receipts.sort(key=lambda receipt: receipt.datetime)
    return receipts


@dataclasses.dataclass(frozen=True)
class _TableKey:
    day: int
    hour: int
    minute: int
    store: str
    line_number: int


@dataclasses.dataclass(frozen=True)
class _TableRow:
    key: Optional[_TableKey]
    item: Optional[ReceiptItem]
    line_number: int

    def is_empty(self) -> bool:
        return self.key is None and self.item is None

    @classmethod
    def parse_line(
            cls,
            line: MonthlyReportLine,
            *,
            logger: Optional[logging.Logger] = None) -> Optional[_TableRow]:
        logger = logger or logging.getLogger(__name__)
        logger.debug(
                f'parse as {cls.__name__}'
                f' "{line.text}" at line {line.line_number}')
        # split
        row_match = re.match(
                r'('
                r'\|(?P<day>[0-9]+)'
                r'\|(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})'
                r'\|(?P<store>[^\|]+)'
                r'|'
                r'\|{3}'
                r')'
                r'('
                r'\|(?P<item>[^\|]+)'
                r'\|(?P<price>-?[0-9]+)'
                r'\|'
                r'|'
                r'\|{3}'
                r')',
                line.text)
        if row_match is None:
            logger.error(
                    'failed to parse'
                    f' "{line.text}" at line {line.line_number}')
            return None
        # key
        key: Optional[_TableKey] = None
        if row_match.group('day') is not None:
            key = _TableKey(
                    day=int(row_match.group('day')),
                    hour=int(row_match.group('hour')),
                    minute=int(row_match.group('minute')),
                    store=row_match.group('store'),
                    line_number=line.line_number)
        # item
        item: Optional[ReceiptItem] = None
        if row_match.group('item') is not None:
            item = ReceiptItem(
                    name=row_match.group('item'),
                    price=int(row_match.group('price')),
                    line_number=line.line_number)
        # row
        row = cls(key=key, item=item, line_number=line.line_number)
        logger.debug(f'row: {row}')
        return row


def _filter_payment_section(
        lines: list[MonthlyReportLine]
) -> Generator[MonthlyReportLine, None, None]:
    in_section = False
    for line in lines:
        # the line is not in payment section
        if not in_section:
            if re.match(r'## 出費', line.text):
                in_section = True
        # the line is in paylemnt section
        else:
            if line.text.startswith('#'):
                in_section = False
                return
            yield line


def _parse_payment_table(
        lines: list[MonthlyReportLine],
        logger: logging.Logger) -> list[list[_TableRow]]:
    header: Final[str] = '|日|時刻|店|商品|価格|'
    alignment: Final[str] = '|--:|--:|:--|:--|--:|'
    state: Literal['header', 'body', 'outer'] = 'outer'
    tables: list[list[_TableRow]] = []
    table: list[_TableRow] = []
    for line in _filter_payment_section(lines):
        logger.debug(f'({state}) "{line.text}" at {line.line_number}')
        match state:
            case 'body':
                if line.text:
                    row = _TableRow.parse_line(line, logger=logger)
                    if row is not None:
                        table.append(row)
                        continue
                state = 'outer'
                tables.append(table)
                table = []
            case 'header':
                if line.text == alignment:
                    state = 'body'
                else:
                    logger.error(f'unexpected row "{line.text}"')
            case 'outer':
                if line.text == header:
                    state = 'header'
    if table:
        tables.append(table)
    return tables


class _PaymentTableParser:
    # pylint: disable=too-many-instance-attributes
    def __init__(
            self,
            year: int,
            month: int,
            logger: logging.Logger) -> None:
        self._year = year
        self._month = month
        self._logger = logger
        # item
        self._receipts: list[Receipt] = []
        # table
        self._is_last_empty = False
        self._is_before_key_empty = False
        self._table_key: Optional[_TableKey] = None
        self._table_items: list[ReceiptItem] = []

    def push(self, row: _TableRow) -> None:
        # empty row
        if row.is_empty():
            if self._is_last_empty:
                self._logger.warning(
                        'consective empty row at '
                        f'{self._year:04}/{self._month:02}.md'
                        f':{row.line_number}')
            self._push_receipt()
            self._is_last_empty = True
            return
        # key
        if row.key is not None:
            self._push_receipt()
            # set temporary key
            self._is_before_key_empty = self._is_last_empty
            self._table_key = row.key
        # item
        if row.item is not None:
            # set item
            self._table_items.append(row.item)
        # is not empty row
        self._is_last_empty = False

    def result(self) -> list[Receipt]:
        self._push_receipt()
        # empty row
        if not self._is_last_empty:
            self._logger.warning(
                    'need an empty row after: '
                    f'{_last_position_message(self._receipts[-1])}')
        return self._receipts

    def _push_receipt(self) -> None:
        if self._table_key is None:
            return
        receipt = Receipt(
                year=self._year,
                month=self._month,
                day=self._table_key.day,
                hour=self._table_key.hour,
                minute=self._table_key.minute,
                store=self._table_key.store,
                items=self._table_items,
                line_number=self._table_key.line_number)
        self._logger.debug(f'new receipt: {receipt}')
        # reset temporary key & items
        self._table_key = None
        self._table_items = []
        # validate datetime
        try:
            receipt.datetime
        except ValueError:
            self._logger.error(
                    f'invalid datetime: {_first_position_message(receipt)}')
            return
        # validate order
        if self._receipts:
            if self._receipts[-1].datetime > receipt.datetime:
                self._logger.warning(
                        f'wrong order: {_first_position_message(receipt)}')
        # validate empty row
        if self._receipts:
            if self._receipts[-1].datetime.day < receipt.datetime.day:
                if not self._is_before_key_empty:
                    self._logger.warning(
                            'need an empty row before: '
                            f'{_first_position_message(receipt)}')
            else:
                if self._is_before_key_empty:
                    self._logger.warning(
                            'need not an empty row before: '
                            f'{_first_position_message(receipt)}')
        else:
            # first row
            if not self._is_before_key_empty:
                self._logger.warning(
                        'need an empty row before: '
                        f'{_first_position_message(receipt)}')
        # add to receipts
        self._receipts.append(receipt)


def _first_position_message(receipt: Receipt) -> str:
    return (f'{receipt.to_table_rows()[0]} '
            f'at {receipt.year:04}/{receipt.month:02}.md'
            f':{receipt.line_number}')


def _last_position_message(receipt: Receipt) -> str:
    return (f'{receipt.to_table_rows()[-1]} '
            f'at {receipt.year:04}/{receipt.month:02}.md'
            f':{receipt.last_line_number}')
