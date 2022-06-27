from __future__ import annotations
import dataclasses
import logging
import pathlib
import re
from typing import Literal, Optional
from ._payment import Receipt, parse_payment


class MonthlyReport:
    def __init__(
            self,
            year: int,
            month: int,
            lines: list[MonthlyReportLine]) -> None:
        self._year = year
        self._month = month
        self._lines = lines

    @classmethod
    def load(
            cls,
            filepath: pathlib.Path,
            *,
            logger: Optional[logging.Logger] = None,
    ) -> Optional[MonthlyReport]:
        filepath = filepath.resolve()
        logger = logger or logging.getLogger(__name__)
        logger.info(f'load "{filepath.as_posix()}"')
        # validate filepath
        filepath_match = re.search(
                r'(?P<year>[0-9]{4})/(?P<month>0[1-9]|1[0-2])\.md$',
                filepath.as_posix())
        if not filepath_match:
            logger.error(f'{filepath.as_posix()} is not YYYY/MM.md')
            return None
        # year, month
        year = int(filepath_match.group('year'))
        month = int(filepath_match.group('month'))
        logger.debug(f'year={year}, month={month}')
        # load file
        logger.debug(f'open "{filepath.as_posix()}"')
        lines: list[MonthlyReportLine] = []
        with filepath.open(encoding='utf-8') as file:
            for i, line in enumerate(file, start=1):
                lines.append(MonthlyReportLine(
                        text=line.removesuffix('\n'),
                        line_number=i))
        # generate
        report = cls(year, month, lines)
        # validate title
        logger.debug(f'title="{report.title()}"')
        title = f'{year}年 {month}月'
        if report.title() != title:
            logger.warning(
                    'unexpected title: '
                    f'"{report.title()}" (expected "{title}")')
        return report

    @property
    def year(self) -> int:
        return self._year

    @property
    def month(self) -> int:
        return self._month

    def text(self) -> str:
        return ''.join(f'{line.text}\n' for line in self._lines)

    def title(self) -> Optional[str]:
        if self._lines:
            if title_match := re.match(
                    r'^# (?P<title>.+)',
                    self._lines[0].text):
                return title_match.group('title')
        return None

    def payment(
            self,
            *,
            logger: Optional[logging.Logger] = None) -> list[Receipt]:
        return parse_payment(
                self.year,
                self.month,
                self._lines,
                logger=logger)


@dataclasses.dataclass(frozen=True)
class MonthlyReportLine:
    text: str
    line_number: int


def find_monthly_reports(
        directory: pathlib.Path,
        *,
        mode: Literal['years', 'months', 'auto'] = 'auto',
        logger: Optional[logging.Logger] = None) -> list[MonthlyReport]:
    logger = logger or logging.getLogger(__name__)
    reports: list[MonthlyReport] = []
    # auto mode
    if mode == 'auto':
        if re.match(r'[0-9]{4}', directory.name):
            mode = 'months'
        else:
            mode = 'years'
    # find years / monthly
    if mode == 'years':
        reports.extend(_find_monthly_reports_years(directory, logger))
    elif mode == 'months':
        reports.extend(_find_monthly_reports_months(directory, logger))
    # sort by old, ..., new
    reports.sort(key=lambda report: (report.year, report.month))
    return reports


def _find_monthly_reports_years(
        directory: pathlib.Path,
        logger: logging.Logger) -> list[MonthlyReport]:
    reports: list[MonthlyReport] = []
    # check if the path is directory
    if not directory.is_dir():
        logger.warning(f'the path "{directory.as_posix()}" is not a directory')
        return reports
    # find YYYY
    for child in directory.iterdir():
        if not child.is_dir():
            continue
        if re.match(r'[0-9]{4}', child.name):
            reports.extend(_find_monthly_reports_months(child, logger))
    return reports


def _find_monthly_reports_months(
        directory: pathlib.Path,
        logger: logging.Logger) -> list[MonthlyReport]:
    reports: list[MonthlyReport] = []
    # check if the path is directory
    if not directory.is_dir():
        logger.warning(f'the path "{directory.as_posix()}" is not a directory')
        return reports
    # check directory name
    if not re.match(r'[0-9]{4}', directory.name):
        logger.warning(f'the directory name "{directory.stem}" is not YYYY')
    # find MM.md
    for child in directory.iterdir():
        if not child.is_file():
            continue
        if re.match(r'(0[1-9]|1[0-2])\.md', child.name):
            report = MonthlyReport.load(child, logger=logger)
            if report is not None:
                reports.append(report)
    return reports
