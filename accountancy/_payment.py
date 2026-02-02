from __future__ import annotations

import dataclasses
import datetime
import logging
import pathlib
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

    def date(self) -> datetime.date:
        return datetime.date(
            year=self.year,
            month=self.month,
            day=self.day,
        )

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
    text_line: Optional[TextLine] = None

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

    def __str__(self) -> str:
        return f"{repr(self.text)} at {self.filename}:{self.line_number}"

    def slice(self, substring: str) -> Optional[Self]:
        if substring not in self.text:
            return None
        return type(self)(
            text=substring,
            filename=self.filename,
            line_number=self.line_number,
        )

    @classmethod
    def load_file(cls, path: pathlib.Path) -> list[Self]:
        lines: list[Self] = []
        with path.open(encoding="utf-8") as file:
            for i, line in enumerate(file, start=1):
                lines.append(
                    cls(
                        text=line.removesuffix("\n"),
                        filename=path.as_posix(),
                        line_number=i,
                    )
                )
        return lines


@dataclasses.dataclass(frozen=True)
class Payment:
    key: PaymentKey
    items: list[PaymentItem]

    def total_price(self) -> int:
        return sum(item.price for item in self.items)

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

    @staticmethod
    def empty_row() -> str:
        return "||||||"

    @staticmethod
    def pattern(
        *,
        date_format: DateFormat = "D",
        allow_empty: bool = False,
    ) -> str:
        # key: YYYY/MM/DD|hh:mm|store or |D|hh:mm|store or |||
        key = PaymentKey.pattern(date_format=date_format)
        empty_key = PaymentKey.pattern(date_format=date_format, empty=True)
        key_pattern = rf"(({key})|({empty_key}))"
        # item: item|price
        item = PaymentItem.pattern()
        empty_item = PaymentItem.pattern(empty=True)
        item_pattern = rf"(({item})|({empty_item}))" if allow_empty else item
        return rf"\|{key_pattern}\|{item_pattern}\|(?P<annotations>.+)?"


@dataclasses.dataclass(frozen=True)
class PaymentTableDate:
    year: int
    month: int


@dataclasses.dataclass(frozen=True)
class PaymentTableKey:
    date: Optional[PaymentTableDate]
    day: int
    hour: int
    minute: int
    store: str

    def to_payment_key(
        self,
        *,
        date: Optional[PaymentTableDate] = None,
    ) -> Optional[PaymentKey]:
        date = self.date or date
        if date is None:
            return None
        return PaymentKey(
            year=date.year,
            month=date.month,
            day=self.day,
            hour=self.hour,
            minute=self.minute,
            store=self.store,
        )


@dataclasses.dataclass(frozen=True)
class PaymentTableRowAnnotations:
    subtotal: Optional[int] = None

    @classmethod
    def parse_text_line(
        cls,
        text_line: TextLine,
        *,
        logger: Optional[logging.Logger] = None,
    ) -> Optional[Self]:
        logger = logger or logging.Logger(__name__)
        annotations = {}
        # split text
        for arg in (arg.strip(" ") for arg in text_line.text.split(",")):
            # subtotal
            if match := re.fullmatch(r"=(?P<subtotal>-?[0-9]+)", arg):
                if "subtotal" in annotations:
                    logger.warning(
                        "There are multiple subtotal annoations: %s",
                        text_line,
                    )
                annotations["subtotal"] = int(match.group("subtotal"))
            # unexpected annotation
            else:
                logger.error("Unexpected annotation %s %s", repr(arg), text_line)
                return None
        return cls(**annotations)


@dataclasses.dataclass(frozen=True)
class PaymentTableRow:
    key: Optional[PaymentTableKey]
    item: Optional[PaymentItem]
    text_line: TextLine
    annotations: Optional[PaymentTableRowAnnotations] = None

    def is_empty(self) -> bool:
        return self.key is None and self.item is None

    @classmethod
    def parse_text_line(
        cls,
        line: TextLine,
        *,
        date: Optional[PaymentTableDate] = None,
        logger: Optional[logging.Logger] = None,
    ) -> Optional[Self]:
        # logger
        logger = logger or logging.getLogger(__name__)
        logger.debug("Parse %s", line)
        # match
        match = re.match(
            Payment.pattern(date_format=_to_date_format(date), allow_empty=True),
            line.text,
        )
        if match is None:
            logger.error("Failed to parse as %s: %s", cls.__name__, line)
            return None
        groups = match.groupdict()
        # key
        key: Optional[PaymentTableKey] = None
        if groups.get("day", None) is not None:
            key = PaymentTableKey(
                date=(
                    date
                    if date is not None
                    else PaymentTableDate(
                        year=int(groups["year"]),
                        month=int(groups["month"]),
                    )
                ),
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
        # annotations
        annotations: Optional[PaymentTableRowAnnotations] = None
        if (
            groups.get("annotations", None) is not None
            and (annotations_text := line.slice(groups["annotations"])) is not None
        ):
            annotations = PaymentTableRowAnnotations.parse_text_line(
                annotations_text,
                logger=logger,
            )
        # row
        row = cls(
            key=key,
            item=item,
            text_line=line,
            annotations=annotations,
        )
        logger.debug("row: %s", row)
        return row


PAYMENT_TABLE_HEADER: Final[str] = "|日|時刻|店|商品|価格|"
PAYMENT_TABLE_ALIGNMENT: Final[str] = "|--:|--:|:--|:--|--:|"


@dataclasses.dataclass(frozen=True)
class PaymentTable:
    date: Optional[PaymentTableDate]
    header: TextLine
    alignment: TextLine
    rows: list[PaymentTableRow]

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(self.header.text)
        lines.append(self.alignment.text)
        lines.extend(row.text_line.text for row in self.rows)
        return "\n".join(lines)

    def to_payments(
        self,
        *,
        formatted: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> list[Payment]:
        logger = logger or logging.Logger(__name__)
        parser = _PaymentTableParser(self.date, formatted, logger)
        for row in self.rows:
            parser.push(row)
        return parser.result()

    @classmethod
    def parse_text_lines(
        cls,
        lines: list[TextLine],
        *,
        date: Optional[PaymentTableDate] = None,
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
                date=date,
                logger=logger,
            )
            if row is None:
                logger.error("Abort parsing on %s", line)
                break
            rows.append(row)
        return cls(
            date=date,
            header=header,
            alignment=alignment,
            rows=rows,
        )


def parse_payments(
    lines: list[TextLine],
    *,
    date: Optional[PaymentTableDate] = None,
    formatted: bool = False,
    logger: Optional[logging.Logger],
) -> list[Payment]:
    logger = logger or logging.getLogger(__name__)

    payments: list[Payment] = []
    for table in search_payment_tables(
        lines,
        date=date,
        logger=logger,
    ):
        payments.extend(
            table.to_payments(
                formatted=formatted,
                logger=logger,
            )
        )
    # sort by old...new
    payments.sort(key=lambda payment: payment.key)
    return payments


def search_payment_tables(
    lines: list[TextLine],
    *,
    header: str = PAYMENT_TABLE_HEADER,
    alignment: str = PAYMENT_TABLE_ALIGNMENT,
    date: Optional[PaymentTableDate] = None,
    logger: Optional[logging.Logger] = None,
) -> Generator[PaymentTable, None, None]:
    logger = logger or logging.getLogger(__name__)
    header_line: Optional[TextLine] = None
    alignment_line: Optional[TextLine] = None
    table_lines: list[TextLine] = []
    row_pattern = re.compile(
        Payment.pattern(
            date_format=_to_date_format(date),
            allow_empty=True,
        )
    )
    for line in lines:
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
                        line,
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
                        date=date,
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
            date=date,
            logger=logger,
        )
        if table is not None:
            yield table


def _to_date_format(date: Optional[PaymentTableDate]) -> DateFormat:
    if date is None:
        return "YYYY/MM/DD"
    return "D"


class _PaymentTableParser:
    def __init__(
        self,
        date: Optional[PaymentTableDate],
        formatted: bool,
        logger: logging.Logger,
    ) -> None:
        self._date = date
        self._formatted = formatted
        self._logger = logger
        # parse
        self._result: list[Payment] = []
        self._last_row: Optional[PaymentTableRow] = None
        self._payment: Optional[Payment] = None

    def push(
        self,
        row: PaymentTableRow,
    ) -> None:
        # update last row
        last_row, self._last_row = self._last_row, row
        # empty row
        if row.key is None and row.item is None:
            if self._payment is not None:
                self._result.append(self._payment)
                self._payment = None
            # format check: consecutive empty rows
            if last_row is not None:
                self._format_check(
                    last_row.is_empty(),
                    "Consecutive empty rows",
                    row.text_line,
                )
        else:
            # format check: first row is empty
            self._format_check(
                last_row is None,
                "The first row is not empty",
                row.text_line,
            )
            # key only
            if row.item is None:
                self._logger.error("The row has only the key: %s", row.text_line)
                return
            # key & item
            if row.key is not None:
                if self._payment is not None:
                    self._result.append(self._payment)
                    self._payment = None
                key = row.key.to_payment_key(date=self._date)
                if key is None:
                    self._logger.error("Failed to parse a key: %s", row.text_line)
                    return
                # check: key has valid datetime
                try:
                    key.datetime()
                except ValueError:
                    self._logger.error(
                        "Invalid datetime: %s",
                        row.text_line,
                    )
                    return
                # format check: The timeline is wrong
                if self._result:
                    # format check: The timeline is wrong
                    self._format_check(
                        self._result[-1].key.datetime() > key.datetime(),
                        "The timeline is wrong",
                        row.text_line,
                    )
                    # format check: An empty row is required between days
                    self._format_check(
                        self._result[-1].key.date() != key.date()
                        and last_row is not None
                        and not last_row.is_empty(),
                        "An empty row is required between days",
                        row.text_line,
                    )
                self._payment = Payment(
                    key=key,
                    items=[],
                )
            # add item to payment
            if self._payment is not None:
                self._payment.items.append(row.item)
            else:
                self._logger.error("The item has no related key: %s", row.text_line)

    def result(self) -> list[Payment]:
        # format check
        if self._last_row is not None:
            # format check: last row is empty
            self._format_check(
                not self._last_row.is_empty(),
                "An empty row is required at the end",
                self._last_row.text_line,
            )
        else:
            # format check: empty table
            self._format_check(
                self._last_row is None,
                "Payment table is empty",
                None,
            )
        # add the last payment to result
        if self._payment is not None:
            self._result.append(self._payment)
        return self._result

    def _format_check(
        self,
        has_error: bool,
        message: str,
        line: Optional[TextLine],
    ) -> None:
        if self._formatted and has_error:
            if line is not None:
                self._logger.warning("%s: %s", message, line)
            else:
                self._logger.warning(message)


def to_payment_table(
    payments: list[Payment],
    *,
    header: str = PAYMENT_TABLE_HEADER,
    alignment: str = PAYMENT_TABLE_ALIGNMENT,
    date_format: DateFormat = "YYYY/MM/DD",
    formatted: bool = False,
) -> list[str]:
    lines: list[str] = []
    last_payment: Optional[Payment] = None
    empty_row = Payment.empty_row()
    # write header & alignment
    lines.append(header)
    lines.append(alignment)
    # first empty row
    if formatted:
        lines.append(empty_row)
    # payments
    for payment in payments:
        # empty row between days
        if (
            formatted
            and last_payment is not None
            and last_payment.key.date() != payment.key.date()
        ):
            lines.append(empty_row)
        lines.extend(payment.to_rows(date_format=date_format))
        last_payment = payment
    # last empty row
    if formatted:
        lines.append(empty_row)
    return lines


def group_payments_by_date(
    payments: list[Payment],
) -> list[tuple[PaymentTableDate, list[Payment]]]:
    # sort by date
    payments.sort(key=lambda payment: payment.key)
    # split
    result: list[tuple[PaymentTableDate, list[Payment]]] = []
    last: Optional[Payment] = None
    for payment in payments:
        if (
            last is not None
            and last.key.year == payment.key.year
            and last.key.month == payment.key.month
        ):
            result[-1][1].append(payment)
        else:
            result.append(
                (
                    PaymentTableDate(
                        year=payment.key.year,
                        month=payment.key.month,
                    ),
                    [payment],
                )
            )
        last = payment
    return result
