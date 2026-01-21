from __future__ import annotations

import dataclasses
import datetime
import logging
import re
from typing import Final, Generator, Literal, Optional, Self


@dataclasses.dataclass(frozen=True, order=True)
class PaymentKey:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    store: str

    def datetime(self) -> datetime.datetime:
        return datetime.datetime(
            year=self.year,
            month=self.month,
            day=self.day,
            hour=self.hour,
            minute=self.minute,
        )

    def to_columns(
        self,
        *,
        skip: bool = False,
    ) -> list[str]:
        if skip:
            return ["", "", ""]
        return [
            f"{self.day}",
            f"{self.hour:02d}:{self.minute:02d}",
            self.store,
        ]


@dataclasses.dataclass(frozen=True)
class PaymentItem:
    name: str
    price: int
    text_line: Optional[TextLine]

    def to_columns(self) -> list[str]:
        return [self.name, f"{self.price}"]


@dataclasses.dataclass(frozen=True)
class TextLine:
    text: str
    filename: str
    line_number: int

    def message(self) -> str:
        return f"{repr(self.text)} at {self.filename}:{self.line_number}"


@dataclasses.dataclass(frozen=True)
class Payment:
    key: PaymentKey
    items: list[PaymentItem]

    def to_table_rows(self) -> list[str]:
        return [
            "|".join(
                [
                    "",
                    *self.key.to_columns(skip=i > 0),
                    *item.to_columns(),
                    "",
                ]
            )
            for i, item in enumerate(self.items)
        ]

    def to_table(self) -> str:
        return "\n".join(self.to_table_rows())


def parse_payment(
    year: int,
    month: int,
    lines: list[TextLine],
    *,
    logger: Optional[logging.Logger],
) -> list[Payment]:
    logger = logger or logging.getLogger(__name__)

    payments: list[Payment] = []
    tables = _parse_payment_table(lines, logger)
    for table in tables:
        parser = _PaymentTableParser(year, month, logger)
        for row in table:
            parser.push(row)
        payments.extend(parser.result())
    # sort by old...new
    payments.sort(key=lambda payment: payment.key)
    return payments


@dataclasses.dataclass(frozen=True)
class _TableKey:
    day: int
    hour: int
    minute: int
    store: str

    def to_payment_key(
        self,
        year: int,
        month: int,
    ) -> PaymentKey:
        return PaymentKey(
            year=year,
            month=month,
            day=self.day,
            hour=self.hour,
            minute=self.minute,
            store=self.store,
        )


@dataclasses.dataclass(frozen=True)
class _TableRow:
    key: Optional[_TableKey]
    item: Optional[PaymentItem]
    text_line: TextLine

    def is_empty(self) -> bool:
        return self.key is None and self.item is None

    @classmethod
    def parse_line(
        cls,
        line: TextLine,
        *,
        logger: Optional[logging.Logger] = None,
    ) -> Optional[Self]:
        logger = logger or logging.getLogger(__name__)
        logger.debug(
            'parse as %s "%s" at line %d',
            cls.__name__,
            line.text,
            line.line_number,
        )
        # split
        row_match = re.match(
            r"("
            r"\|(?P<day>[0-9]+)"
            r"\|(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})"
            r"\|(?P<store>[^\|]+)"
            r"|"
            r"\|{3}"
            r")"
            r"("
            r"\|(?P<item>[^\|]+)"
            r"\|(?P<price>-?[0-9]+)"
            r"\|"
            r"|"
            r"\|{3}"
            r")",
            line.text,
        )
        if row_match is None:
            logger.error(
                'failed to parse "%s" at line %d',
                line.text,
                line.line_number,
            )
            return None
        # key
        key: Optional[_TableKey] = None
        if row_match.group("day") is not None:
            key = _TableKey(
                day=int(row_match.group("day")),
                hour=int(row_match.group("hour")),
                minute=int(row_match.group("minute")),
                store=row_match.group("store"),
            )
        # item
        item: Optional[PaymentItem] = None
        if row_match.group("item") is not None:
            item = PaymentItem(
                name=row_match.group("item"),
                price=int(row_match.group("price")),
                text_line=line,
            )
        # row
        row = cls(
            key=key,
            item=item,
            text_line=line,
        )
        logger.debug("row: %s", row)
        return row


def _filter_payment_section(
    lines: list[TextLine],
) -> Generator[TextLine, None, None]:
    in_section = False
    for line in lines:
        # the line is not in payment section
        if not in_section:
            if re.match(r"## 出費", line.text):
                in_section = True
        # the line is in paylemnt section
        else:
            if line.text.startswith("#"):
                in_section = False
                return
            yield line


def _parse_payment_table(
    lines: list[TextLine],
    logger: logging.Logger,
) -> list[list[_TableRow]]:
    header: Final[str] = "|日|時刻|店|商品|価格|"
    alignment: Final[str] = "|--:|--:|:--|:--|--:|"
    state: Literal["header", "body", "outer"] = "outer"
    tables: list[list[_TableRow]] = []
    table: list[_TableRow] = []
    for line in _filter_payment_section(lines):
        logger.debug(f'({state}) "{line.text}" at {line.line_number}')
        match state:
            case "body":
                if line.text:
                    row = _TableRow.parse_line(line, logger=logger)
                    if row is not None:
                        table.append(row)
                        continue
                state = "outer"
                tables.append(table)
                table = []
            case "header":
                if line.text == alignment:
                    state = "body"
                else:
                    logger.error('unexpected row "%s"', line.text)
            case "outer":
                if line.text == header:
                    state = "header"
    if table:
        tables.append(table)
    return tables


class _PaymentTableParser:
    # pylint: disable=too-many-instance-attributes
    def __init__(
        self,
        year: int,
        month: int,
        logger: logging.Logger,
    ) -> None:
        self._year = year
        self._month = month
        self._logger = logger
        # item
        self._payments: list[Payment] = []
        # table
        self._is_last_empty = False
        self._is_before_key_empty = False
        self._table_key: Optional[_TableKey] = None
        self._table_items: list[PaymentItem] = []

    def push(self, row: _TableRow) -> None:
        # empty row
        if row.is_empty():
            if self._is_last_empty:
                self._logger.warning(
                    "consective empty row: %s",
                    row.text_line.message(),
                )
            self._push_payment()
            self._is_last_empty = True
            return
        # key
        if row.key is not None:
            self._push_payment()
            # set temporary key
            self._is_before_key_empty = self._is_last_empty
            self._table_key = row.key
        # item
        if row.item is not None:
            # set item
            self._table_items.append(row.item)
        # is not empty row
        self._is_last_empty = False

    def result(self) -> list[Payment]:
        self._push_payment()
        # empty row
        if not self._is_last_empty:
            self._logger.warning("An empty row is required at the end")
        return self._payments

    def _push_payment(self) -> None:
        if self._table_key is None:
            return
        payment = Payment(
            key=self._table_key.to_payment_key(
                year=self._year,
                month=self._month,
            ),
            items=self._table_items,
        )
        self._logger.debug("new payment: %s", payment)
        # reset temporary key & items
        self._table_key = None
        self._table_items = []
        # validate datetime
        try:
            payment.key.datetime()
        except ValueError:
            self._logger.error(
                "invalid datetime: %s",
                _first_position_message(payment),
            )
            return
        # validate order
        if self._payments:
            if self._payments[-1].key.datetime() > payment.key.datetime():
                self._logger.warning(
                    "wrong order: %s",
                    _first_position_message(payment),
                )
        # validate empty row
        if self._payments:
            if self._payments[-1].key.day < payment.key.day:
                if not self._is_before_key_empty:
                    self._logger.warning(
                        "need an empty row before: %s",
                        _first_position_message(payment),
                    )
            else:
                if self._is_before_key_empty:
                    self._logger.warning(
                        "need not an empty row before: %s",
                        _first_position_message(payment),
                    )
        else:
            # first row
            if not self._is_before_key_empty:
                self._logger.warning(
                    "need an empty row before: %s",
                    _first_position_message(payment),
                )
        # add to payments
        self._payments.append(payment)


def _first_position_message(payment: Payment) -> str:
    text_line = payment.items[0].text_line
    if text_line is None:
        return "---"
    return text_line.message()


def _last_position_message(payment: Payment) -> str:
    text_line = payment.items[-1].text_line
    if text_line is None:
        return "---"
    return text_line.message()
