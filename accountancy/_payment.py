from __future__ import annotations

import dataclasses
import datetime
import logging
import re
from typing import Final, Generator, Literal, Optional, Self

DateFormat = Literal["YYYY/MM/DD", "D"]


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
        date_format: DateFormat = "D",
        skip: bool = False,
    ) -> list[str]:
        if skip:
            return ["", "", ""]
        match date_format:
            case "D":
                date = f"{self.day}"
            case "YYYY/MM/DD":
                date = f"{self.year:04d}/{self.month:02d}/{self.day:02d}"
        return [
            date,
            f"{self.hour:02d}:{self.minute:02d}",
            self.store,
        ]

    @staticmethod
    def pattern(
        *,
        date_format: DateFormat = "D",
        empty: bool = False,
    ) -> str:
        # DD|hh:mm|store or YYYY/MM/DD|hh:mm|store
        match date_format:
            case "D":
                date = r"(?P<day>[0-9]+)"
            case "YYYY/MM/DD":
                date = r"(?P<year>[0-9]{4})/(?P<month>[0-9]{2})/(?P<day>[0-9]{2})"
        time = r"(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})"
        store = r"(?P<store>[^|]+)"
        if empty:
            return r"\|{2}"
        return rf"{date}\|{time}\|{store}"


@dataclasses.dataclass(frozen=True)
class PaymentItem:
    name: str
    price: int
    text_line: Optional[TextLine]

    def to_columns(self) -> list[str]:
        return [self.name, f"{self.price}"]

    @staticmethod
    def pattern(
        *,
        empty: bool = False,
    ) -> str:
        # item|price
        item = r"(?P<item>[^|]+)"
        price = r"(?P<price>-?[0-9]+)"
        if empty:
            return r"\|"
        return rf"{item}\|{price}"


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

    def to_rows(
        self,
        *,
        date_format: DateFormat = "D",
    ) -> list[str]:
        return [
            "|".join(
                [
                    "",
                    *self.key.to_columns(date_format=date_format, skip=i > 0),
                    *item.to_columns(),
                    "",
                ]
            )
            for i, item in enumerate(self.items)
        ]

    def to_table(self) -> str:
        return "\n".join(self.to_table_rows())

    @staticmethod
    def pattern(
        *,
        date_format: DateFormat = "D",
        allow_empty: bool = False,
    ) -> str:
        key = PaymentKey.pattern(date_format=date_format)
        empty_key = PaymentKey.pattern(date_format=date_format, empty=True)
        item = PaymentItem.pattern()
        empty_item = PaymentItem.pattern(empty=True)
        if allow_empty:
            return rf"\|(({key})|({empty_key}))\|(({item})|({empty_item}))\|"
        return rf"\|(({key})|({empty_key}))\|{item}\|"


def parse_payment(
    year: int,
    month: int,
    lines: list[TextLine],
    *,
    date_format: DateFormat = "D",
    logger: Optional[logging.Logger],
) -> list[Payment]:
    logger = logger or logging.getLogger(__name__)

    payments: list[Payment] = []
    for table in search_payment_tables(
        lines,
        date_format=date_format,
        logger=logger,
    ):
        parser = _PaymentTableParser(year, month, logger)
        for row in table.rows:
            parser.push(row)
        payments.extend(parser.result())
    # sort by old...new
    payments.sort(key=lambda payment: payment.key)
    return payments


@dataclasses.dataclass(frozen=True)
class PaymentTableKey:
    year: Optional[int]
    month: Optional[int]
    day: int
    hour: int
    minute: int
    store: str

    def to_payment_key(
        self,
        *,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> Optional[PaymentKey]:
        year = self.year if self.year is not None else year
        month = self.month if self.month is not None else month
        if year is None or month is None:
            return None
        return PaymentKey(
            year=year,
            month=month,
            day=self.day,
            hour=self.hour,
            minute=self.minute,
            store=self.store,
        )


@dataclasses.dataclass(frozen=True)
class PaymentTableRow:
    key: Optional[PaymentTableKey]
    item: Optional[PaymentItem]
    text_line: TextLine

    def is_empty(self) -> bool:
        return self.key is None and self.item is None

    @classmethod
    def parse_text_line(
        cls,
        line: TextLine,
        *,
        date_format: DateFormat = "D",
        logger: Optional[logging.Logger] = None,
    ) -> Optional[Self]:
        # logger
        logger = logger or logging.getLogger(__name__)
        logger.debug("Parse %s", line.message())
        # match
        match = re.match(
            Payment.pattern(date_format=date_format, allow_empty=True),
            line.text,
        )
        if match is None:
            logger.error(
                "Failed to parse as %s: %s",
                cls.__name__,
                line.message(),
            )
            return None
        groups = match.groupdict()
        # key
        key: Optional[PaymentTableKey] = None
        if groups.get("day", None) is not None:
            key = PaymentTableKey(
                year=int(groups["year"]) if "year" in groups else None,
                month=int(groups["month"]) if "month" in groups else None,
                day=int(groups["day"]),
                hour=int(groups["hour"]),
                minute=int(groups["minute"]),
                store=groups["store"],
            )
        # item
        item: Optional[PaymentItem] = None
        if groups.get("item", None) is not None:
            item = PaymentItem(
                name=groups["item"],
                price=int(groups["price"]),
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


PAYMENT_TABLE_HEADER: Final[str] = "|日|時刻|店|商品|価格|"
PAYMENT_TABLE_ALIGNMENT: Final[str] = "|--:|--:|:--|:--|--:|"


@dataclasses.dataclass(frozen=True)
class PaymentTable:
    header: TextLine
    alignment: TextLine
    rows: list[PaymentTableRow]

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(self.header.text)
        lines.append(self.alignment.text)
        lines.extend(row.text_line.text for row in self.rows)
        return "\n".join(lines)

    @classmethod
    def parse_text_lines(
        cls,
        lines: list[TextLine],
        *,
        date_format: DateFormat = "D",
        logger: Optional[logging.Logger] = None,
    ) -> Optional[Self]:
        # logger
        logger = logger or logging.getLogger(__name__)
        # header & alignment
        if len(lines) < 2:
            logger.error(
                "Payment tables must have at least 2 rows: "
                "a header line and an alignment line"
            )
            return None
        header, alignment, *body = lines
        # rows
        rows: list[PaymentTableRow] = []
        for line in body:
            row = PaymentTableRow.parse_text_line(
                line,
                date_format=date_format,
                logger=logger,
            )
            if row is None:
                logger.error("Abort parsing on %s", line.message())
                break
            rows.append(row)
        return cls(
            header=header,
            alignment=alignment,
            rows=rows,
        )


def search_payment_tables(
    lines: list[TextLine],
    *,
    header: str = PAYMENT_TABLE_HEADER,
    alignment: str = PAYMENT_TABLE_ALIGNMENT,
    date_format: DateFormat = "D",
    logger: Optional[logging.Logger] = None,
) -> Generator[PaymentTable, None, None]:
    logger = logger or logging.getLogger(__name__)
    header_line: Optional[TextLine] = None
    alignment_line: Optional[TextLine] = None
    table_lines: list[TextLine] = []
    row_pattern = re.compile(
        Payment.pattern(
            date_format=date_format,
            allow_empty=True,
        )
    )
    for line in _filter_payment_section(lines):
        # find header
        if header_line is None:
            if line.text == header:
                header_line = line
                table_lines.append(line)
        else:
            # find alignment
            if alignment_line is None:
                if line.text == alignment:
                    alignment_line = line
                    table_lines.append(line)
                else:
                    logger.error(
                        "An alignment line(%s) is expected but got %s",
                        alignment,
                        line.message(),
                    )
                    # reset
                    header_line = None
                    table_lines = []
            else:
                # rows
                if row_pattern.match(line.text):
                    table_lines.append(line)
                else:
                    # table
                    table = PaymentTable.parse_text_lines(
                        table_lines,
                        date_format=date_format,
                        logger=logger,
                    )
                    if table is not None:
                        yield table
                    # reset
                    header_line = None
                    alignment_line = None
                    table_lines = []
    # return last table
    if header_line is not None and alignment_line is not None:
        table = PaymentTable.parse_text_lines(
            table_lines,
            date_format=date_format,
            logger=logger,
        )
        if table is not None:
            yield table


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
        self._table_key: Optional[PaymentTableKey] = None
        self._table_items: list[PaymentItem] = []

    def push(self, row: PaymentTableRow) -> None:
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
        key = self._table_key.to_payment_key(
            year=self._year,
            month=self._month,
        )
        if key is None:
            return
        payment = Payment(
            key=key,
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
