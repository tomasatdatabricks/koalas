#
# Copyright (C) 2019 Databricks, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
Wrappers around spark that correspond to common pandas functions.
"""
from typing import Optional, Union
from collections import OrderedDict
from collections.abc import Iterable
import itertools

import numpy as np
import pandas as pd

from pyspark.sql import functions as F
from pyspark.sql.types import ByteType, ShortType, IntegerType, LongType, FloatType, \
    DoubleType, BooleanType, TimestampType, DecimalType, StringType, DateType, StructType

from databricks import koalas as ks  # For running doctests and reference resolution in PyCharm.
from databricks.koalas.utils import default_session
from databricks.koalas.frame import DataFrame, _reduce_spark_multi
from databricks.koalas.typedef import Col, pandas_wraps
from databricks.koalas.series import Series, _col


def from_pandas(pobj: Union['pd.DataFrame', 'pd.Series']) -> Union['Series', 'DataFrame']:
    """Create a Koalas DataFrame or Series from a pandas DataFrame or Series.

    This is similar to Spark's `SparkSession.createDataFrame()` with pandas DataFrame,
    but this also works with pandas Series and picks the index.

    Parameters
    ----------
    pobj : pandas.DataFrame or pandas.Series
        pandas DataFrame or Series to read.

    Returns
    -------
    Series or DataFrame
        If a pandas Series is passed in, this function returns a Koalas Series.
        If a pandas DataFrame is passed in, this function returns a Koalas DataFrame.
    """
    if isinstance(pobj, pd.Series):
        return Series(pobj)
    elif isinstance(pobj, pd.DataFrame):
        return DataFrame(pobj)
    else:
        raise ValueError("Unknown data type: {}".format(type(pobj)))


def sql(query: str) -> DataFrame:
    """
    Execute a SQL query and return the result as a Koalas DataFrame.

    Parameters
    ----------
    query : str
        the SQL query

    Returns
    -------
    DataFrame

    Examples
    --------
    >>> ks.sql("select * from range(10) where id > 7")
       id
    0   8
    1   9
    """
    return DataFrame(default_session().sql(query))


def range(start: int,
          end: Optional[int] = None,
          step: int = 1,
          num_partitions: Optional[int] = None) -> DataFrame:
    """
    Create a DataFrame with some range of numbers.

    The resulting DataFrame has a single int64 column named `id`, containing elements in a range
    from ``start`` to ``end`` (exclusive) with step value ``step``. If only the first parameter
    (i.e. start) is specified, we treat it as the end value with the start value being 0.

    This is similar to the range function in SparkSession and is used primarily for testing.

    Parameters
    ----------
    start : int
        the start value (inclusive)
    end : int, optional
        the end value (exclusive)
    step : int, optional, default 1
        the incremental step
    num_partitions : int, optional
        the number of partitions of the DataFrame

    Returns
    -------
    DataFrame

    Examples
    --------
    When the first parameter is specified, we generate a range of values up till that number.

    >>> ks.range(5)
       id
    0   0
    1   1
    2   2
    3   3
    4   4

    When start, end, and step are specified:

    >>> ks.range(start = 100, end = 200, step = 20)
        id
    0  100
    1  120
    2  140
    3  160
    4  180
    """
    sdf = default_session().range(start=start, end=end, step=step, numPartitions=num_partitions)
    return DataFrame(sdf)


def read_csv(path, header='infer', names=None, usecols=None,
             mangle_dupe_cols=True, parse_dates=False, comment=None):
    """Read CSV (comma-separated) file into DataFrame.

    Parameters
    ----------
    path : str
        The path string storing the CSV file to be read.
    header : int, list of int, default ‘infer’
        Whether to to use as the column names, and the start of the data.
        Default behavior is to infer the column names: if no names are passed
        the behavior is identical to `header=0` and column names are inferred from
        the first line of the file, if column names are passed explicitly then
        the behavior is identical to `header=None`. Explicitly pass `header=0` to be
        able to replace existing names
    names : array-like, optional
        List of column names to use. If file contains no header row, then you should
        explicitly pass `header=None`. Duplicates in this list will cause an error to be issued.
    usecols : list-like or callable, optional
        Return a subset of the columns. If list-like, all elements must either be
        positional (i.e. integer indices into the document columns) or strings that
        correspond to column names provided either by the user in names or inferred
        from the document header row(s).
        If callable, the callable function will be evaluated against the column names,
        returning names where the callable function evaluates to `True`.
    mangle_dupe_cols : bool, default True
        Duplicate columns will be specified as 'X0', 'X1', ... 'XN', rather
        than 'X' ... 'X'. Passing in False will cause data to be overwritten if
        there are duplicate names in the columns.
        Currently only `True` is allowed.
    parse_dates : boolean or list of ints or names or list of lists or dict, default `False`.
        Currently only `False` is allowed.
    comment: str, optional
        Indicates the line should not be parsed.

    Returns
    -------
    DataFrame

    Examples
    --------
    >>> ks.read_csv('data.csv')  # doctest: +SKIP
    """
    if mangle_dupe_cols is not True:
        raise ValueError("mangle_dupe_cols can only be `True`: %s" % mangle_dupe_cols)
    if parse_dates is not False:
        raise ValueError("parse_dates can only be `False`: %s" % parse_dates)

    if usecols is not None and not callable(usecols):
        usecols = list(usecols)
    if usecols is None or callable(usecols) or len(usecols) > 0:
        reader = default_session().read.option("inferSchema", "true")

        if header == 'infer':
            header = 0 if names is None else None
        if header == 0:
            reader.option("header", True)
        elif header is None:
            reader.option("header", False)
        else:
            raise ValueError("Unknown header argument {}".format(header))

        if comment is not None:
            if not isinstance(comment, str) or len(comment) != 1:
                raise ValueError("Only length-1 comment characters supported")
            reader.option("comment", comment)

        sdf = reader.csv(path)

        if header is None:
            sdf = sdf.selectExpr(*["`%s` as `%s`" % (field.name, i)
                                   for i, field in enumerate(sdf.schema)])
        if names is not None:
            names = list(names)
            if len(set(names)) != len(names):
                raise ValueError('Found non-unique column index')
            if len(names) != len(sdf.schema):
                raise ValueError('Names do not match the number of columns: %d' % len(names))
            sdf = sdf.selectExpr(*["`%s` as `%s`" % (field.name, name)
                                   for field, name in zip(sdf.schema, names)])

        if usecols is not None:
            if callable(usecols):
                cols = [field.name for field in sdf.schema if usecols(field.name)]
                missing = []
            elif all(isinstance(col, int) for col in usecols):
                cols = [field.name for i, field in enumerate(sdf.schema) if i in usecols]
                missing = [col for col in usecols
                           if col >= len(sdf.schema) or sdf.schema[col].name not in cols]
            elif all(isinstance(col, str) for col in usecols):
                cols = [field.name for field in sdf.schema if field.name in usecols]
                missing = [col for col in usecols if col not in cols]
            else:
                raise ValueError("'usecols' must either be list-like of all strings, "
                                 "all unicode, all integers or a callable.")
            if len(missing) > 0:
                raise ValueError('Usecols do not match columns, columns expected but not '
                                 'found: %s' % missing)

            if len(cols) > 0:
                sdf = sdf.select(cols)
            else:
                sdf = default_session().createDataFrame([], schema=StructType())
    else:
        sdf = default_session().createDataFrame([], schema=StructType())
    return DataFrame(sdf)


def read_parquet(path, columns=None):
    """Load a parquet object from the file path, returning a DataFrame.

    Parameters
    ----------
    path : string
        File path
    columns : list, default=None
        If not None, only these columns will be read from the file.

    Returns
    -------
    DataFrame

    Examples
    --------
    >>> ks.read_parquet('data.parquet', columns=['name', 'gender'])  # doctest: +SKIP
    """
    if columns is not None:
        columns = list(columns)
    if columns is None or len(columns) > 0:
        sdf = default_session().read.parquet(path)
        if columns is not None:
            fields = [field.name for field in sdf.schema]
            cols = [col for col in columns if col in fields]
            if len(cols) > 0:
                sdf = sdf.select(cols)
            else:
                sdf = default_session().createDataFrame([], schema=StructType())
    else:
        sdf = default_session().createDataFrame([], schema=StructType())
    return DataFrame(sdf)


def read_clipboard(sep=r'\s+', **kwargs):
    r"""
    Read text from clipboard and pass to read_csv. See read_csv for the
    full argument list

    Parameters
    ----------
    sep : str, default '\s+'
        A string or regex delimiter. The default of '\s+' denotes
        one or more whitespace characters.

    Returns
    -------
    parsed : DataFrame
    """
    return from_pandas(pd.read_clipboard(sep, **kwargs))


def read_excel(io, sheet_name=0, header=0, names=None, index_col=None, usecols=None, squeeze=False,
               dtype=None, engine=None, converters=None, true_values=None, false_values=None,
               skiprows=None, nrows=None, na_values=None, keep_default_na=True, verbose=False,
               parse_dates=False, date_parser=None, thousands=None, comment=None, skipfooter=0,
               convert_float=True, mangle_dupe_cols=True, **kwds):
    """
    Read an Excel file into a Koalas DataFrame.

    Support both `xls` and `xlsx` file extensions from a local filesystem or URL.
    Support an option to read a single sheet or a list of sheets.

    Parameters
    ----------
    io : str, file descriptor, pathlib.Path, ExcelFile or xlrd.Book
        The string could be a URL. Valid URL schemes include http, ftp, s3,
        gcs, and file. For file URLs, a host is expected. For instance, a local
        file could be /path/to/workbook.xlsx.
    sheet_name : str, int, list, or None, default 0
        Strings are used for sheet names. Integers are used in zero-indexed
        sheet positions. Lists of strings/integers are used to request
        multiple sheets. Specify None to get all sheets.

        Available cases:

        * Defaults to ``0``: 1st sheet as a `DataFrame`
        * ``1``: 2nd sheet as a `DataFrame`
        * ``"Sheet1"``: Load sheet with name "Sheet1"
        * ``[0, 1, "Sheet5"]``: Load first, second and sheet named "Sheet5"
          as a dict of `DataFrame`
        * None: All sheets.

    header : int, list of int, default 0
        Row (0-indexed) to use for the column labels of the parsed
        DataFrame. If a list of integers is passed those row positions will
        be combined into a ``MultiIndex``. Use None if there is no header.
    names : array-like, default None
        List of column names to use. If file contains no header row,
        then you should explicitly pass header=None.
    index_col : int, list of int, default None
        Column (0-indexed) to use as the row labels of the DataFrame.
        Pass None if there is no such column.  If a list is passed,
        those columns will be combined into a ``MultiIndex``.  If a
        subset of data is selected with ``usecols``, index_col
        is based on the subset.
    usecols : int, str, list-like, or callable default None
        Return a subset of the columns.

        * If None, then parse all columns.
        * If str, then indicates comma separated list of Excel column letters
          and column ranges (e.g. "A:E" or "A,C,E:F"). Ranges are inclusive of
          both sides.
        * If list of int, then indicates list of column numbers to be parsed.
        * If list of string, then indicates list of column names to be parsed.
        * If callable, then evaluate each column name against it and parse the
          column if the callable returns ``True``.
    squeeze : bool, default False
        If the parsed data only contains one column then return a Series.
    dtype : Type name or dict of column -> type, default None
        Data type for data or columns. E.g. {'a': np.float64, 'b': np.int32}
        Use `object` to preserve data as stored in Excel and not interpret dtype.
        If converters are specified, they will be applied INSTEAD
        of dtype conversion.
    engine : str, default None
        If io is not a buffer or path, this must be set to identify io.
        Acceptable values are None or xlrd.
    converters : dict, default None
        Dict of functions for converting values in certain columns. Keys can
        either be integers or column labels, values are functions that take one
        input argument, the Excel cell content, and return the transformed
        content.
    true_values : list, default None
        Values to consider as True.
    false_values : list, default None
        Values to consider as False.
    skiprows : list-like
        Rows to skip at the beginning (0-indexed).
    nrows : int, default None
        Number of rows to parse.
    na_values : scalar, str, list-like, or dict, default None
        Additional strings to recognize as NA/NaN. If dict passed, specific
        per-column NA values. By default the following values are interpreted
        as NaN.
    keep_default_na : bool, default True
        If na_values are specified and keep_default_na is False the default NaN
        values are overridden, otherwise they're appended to.
    verbose : bool, default False
        Indicate number of NA values placed in non-numeric columns.
    parse_dates : bool, list-like, or dict, default False
        The behavior is as follows:

        * bool. If True -> try parsing the index.
        * list of int or names. e.g. If [1, 2, 3] -> try parsing columns 1, 2, 3
          each as a separate date column.
        * list of lists. e.g.  If [[1, 3]] -> combine columns 1 and 3 and parse as
          a single date column.
        * dict, e.g. {{'foo' : [1, 3]}} -> parse columns 1, 3 as date and call
          result 'foo'

        If a column or index contains an unparseable date, the entire column or
        index will be returned unaltered as an object data type. For non-standard
        datetime parsing, use ``pd.to_datetime`` after ``pd.read_csv``

        Note: A fast-path exists for iso8601-formatted dates.
    date_parser : function, optional
        Function to use for converting a sequence of string columns to an array of
        datetime instances. The default uses ``dateutil.parser.parser`` to do the
        conversion. Koalas will try to call `date_parser` in three different ways,
        advancing to the next if an exception occurs: 1) Pass one or more arrays
        (as defined by `parse_dates`) as arguments; 2) concatenate (row-wise) the
        string values from the columns defined by `parse_dates` into a single array
        and pass that; and 3) call `date_parser` once for each row using one or
        more strings (corresponding to the columns defined by `parse_dates`) as
        arguments.
    thousands : str, default None
        Thousands separator for parsing string columns to numeric.  Note that
        this parameter is only necessary for columns stored as TEXT in Excel,
        any numeric columns will automatically be parsed, regardless of display
        format.
    comment : str, default None
        Comments out remainder of line. Pass a character or characters to this
        argument to indicate comments in the input file. Any data between the
        comment string and the end of the current line is ignored.
    skipfooter : int, default 0
        Rows at the end to skip (0-indexed).
    convert_float : bool, default True
        Convert integral floats to int (i.e., 1.0 --> 1). If False, all numeric
        data will be read in as floats: Excel stores all numbers as floats
        internally.
    mangle_dupe_cols : bool, default True
        Duplicate columns will be specified as 'X', 'X.1', ...'X.N', rather than
        'X'...'X'. Passing in False will cause data to be overwritten if there
        are duplicate names in the columns.
    **kwds : optional
        Optional keyword arguments can be passed to ``TextFileReader``.

    Returns
    -------
    DataFrame or dict of DataFrames
        DataFrame from the passed in Excel file. See notes in sheet_name
        argument for more information on when a dict of DataFrames is returned.

    See Also
    --------
    DataFrame.to_excel : Write DataFrame to an Excel file.
    DataFrame.to_csv : Write DataFrame to a comma-separated values (csv) file.
    read_csv : Read a comma-separated values (csv) file into DataFrame.

    Examples
    --------
    The file can be read using the file name as string or an open file object:

    >>> ks.read_excel('tmp.xlsx', index_col=0)  # doctest: +SKIP
           Name  Value
    0   string1      1
    1   string2      2
    2  #Comment      3

    >>> ks.read_excel(open('tmp.xlsx', 'rb'),
    ...               sheet_name='Sheet3')  # doctest: +SKIP
       Unnamed: 0      Name  Value
    0           0   string1      1
    1           1   string2      2
    2           2  #Comment      3

    Index and header can be specified via the `index_col` and `header` arguments

    >>> ks.read_excel('tmp.xlsx', index_col=None, header=None)  # doctest: +SKIP
         0         1      2
    0  NaN      Name  Value
    1  0.0   string1      1
    2  1.0   string2      2
    3  2.0  #Comment      3

    Column types are inferred but can be explicitly specified

    >>> ks.read_excel('tmp.xlsx', index_col=0,
    ...               dtype={'Name': str, 'Value': float})  # doctest: +SKIP
           Name  Value
    0   string1    1.0
    1   string2    2.0
    2  #Comment    3.0

    True, False, and NA values, and thousands separators have defaults,
    but can be explicitly specified, too. Supply the values you would like
    as strings or lists of strings!

    >>> ks.read_excel('tmp.xlsx', index_col=0,
    ...               na_values=['string1', 'string2'])  # doctest: +SKIP
           Name  Value
    0      None      1
    1      None      2
    2  #Comment      3

    Comment lines in the excel input file can be skipped using the `comment` kwarg

    >>> ks.read_excel('tmp.xlsx', index_col=0, comment='#')  # doctest: +SKIP
          Name  Value
    0  string1    1.0
    1  string2    2.0
    2     None    NaN
    """
    pdfs = pd.read_excel(
        io=io, sheet_name=sheet_name, header=header, names=names, index_col=index_col,
        usecols=usecols, squeeze=squeeze, dtype=dtype, engine=engine, converters=converters,
        true_values=true_values, false_values=false_values, skiprows=skiprows, nrows=nrows,
        na_values=na_values, keep_default_na=keep_default_na, verbose=verbose,
        parse_dates=parse_dates, date_parser=date_parser, thousands=thousands, comment=comment,
        skipfooter=skipfooter, convert_float=convert_float, mangle_dupe_cols=mangle_dupe_cols,
        kwds=kwds)
    if isinstance(pdfs, dict):
        return OrderedDict([(key, from_pandas(value)) for key, value in pdfs.items()])
    else:
        return from_pandas(pdfs)


def read_html(io, match='.+', flavor=None, header=None, index_col=None,
              skiprows=None, attrs=None, parse_dates=False,
              thousands=',', encoding=None,
              decimal='.', converters=None, na_values=None,
              keep_default_na=True, displayed_only=True):
    r"""Read HTML tables into a ``list`` of ``DataFrame`` objects.

    Parameters
    ----------
    io : str or file-like
        A URL, a file-like object, or a raw string containing HTML. Note that
        lxml only accepts the http, ftp and file url protocols. If you have a
        URL that starts with ``'https'`` you might try removing the ``'s'``.

    match : str or compiled regular expression, optional
        The set of tables containing text matching this regex or string will be
        returned. Unless the HTML is extremely simple you will probably need to
        pass a non-empty string here. Defaults to '.+' (match any non-empty
        string). The default value will return all tables contained on a page.
        This value is converted to a regular expression so that there is
        consistent behavior between Beautiful Soup and lxml.

    flavor : str or None, container of strings
        The parsing engine to use. 'bs4' and 'html5lib' are synonymous with
        each other, they are both there for backwards compatibility. The
        default of ``None`` tries to use ``lxml`` to parse and if that fails it
        falls back on ``bs4`` + ``html5lib``.

    header : int or list-like or None, optional
        The row (or list of rows for a :class:`~ks.MultiIndex`) to use to
        make the columns headers.

    index_col : int or list-like or None, optional
        The column (or list of columns) to use to create the index.

    skiprows : int or list-like or slice or None, optional
        0-based. Number of rows to skip after parsing the column integer. If a
        sequence of integers or a slice is given, will skip the rows indexed by
        that sequence.  Note that a single element sequence means 'skip the nth
        row' whereas an integer means 'skip n rows'.

    attrs : dict or None, optional
        This is a dictionary of attributes that you can pass to use to identify
        the table in the HTML. These are not checked for validity before being
        passed to lxml or Beautiful Soup. However, these attributes must be
        valid HTML table attributes to work correctly. For example, ::

            attrs = {'id': 'table'}

        is a valid attribute dictionary because the 'id' HTML tag attribute is
        a valid HTML attribute for *any* HTML tag as per `this document
        <http://www.w3.org/TR/html-markup/global-attributes.html>`__. ::

            attrs = {'asdf': 'table'}

        is *not* a valid attribute dictionary because 'asdf' is not a valid
        HTML attribute even if it is a valid XML attribute.  Valid HTML 4.01
        table attributes can be found `here
        <http://www.w3.org/TR/REC-html40/struct/tables.html#h-11.2>`__. A
        working draft of the HTML 5 spec can be found `here
        <http://www.w3.org/TR/html-markup/table.html>`__. It contains the
        latest information on table attributes for the modern web.

    parse_dates : bool, optional
        See :func:`~ks.read_csv` for more details.

    thousands : str, optional
        Separator to use to parse thousands. Defaults to ``','``.

    encoding : str or None, optional
        The encoding used to decode the web page. Defaults to ``None``.``None``
        preserves the previous encoding behavior, which depends on the
        underlying parser library (e.g., the parser library will try to use
        the encoding provided by the document).

    decimal : str, default '.'
        Character to recognize as decimal point (e.g. use ',' for European
        data).

    converters : dict, default None
        Dict of functions for converting values in certain columns. Keys can
        either be integers or column labels, values are functions that take one
        input argument, the cell (not column) content, and return the
        transformed content.

    na_values : iterable, default None
        Custom NA values

    keep_default_na : bool, default True
        If na_values are specified and keep_default_na is False the default NaN
        values are overridden, otherwise they're appended to

    displayed_only : bool, default True
        Whether elements with "display: none" should be parsed

    Returns
    -------
    dfs : list of DataFrames

    See Also
    --------
    read_csv
    """
    pdfs = pd.read_html(
        io=io, match=match, flavor=flavor, header=header, index_col=index_col, skiprows=skiprows,
        attrs=attrs, parse_dates=parse_dates, thousands=thousands, encoding=encoding,
        decimal=decimal, converters=converters, na_values=na_values,
        keep_default_na=keep_default_na, displayed_only=displayed_only)
    return [from_pandas(pdf) for pdf in pdfs]


def to_datetime(arg, errors='raise', format=None, infer_datetime_format=False):
    """
    Convert argument to datetime.

    Parameters
    ----------
    arg : integer, float, string, datetime, list, tuple, 1-d array, Series
           or DataFrame/dict-like

    errors : {'ignore', 'raise', 'coerce'}, default 'raise'

        - If 'raise', then invalid parsing will raise an exception
        - If 'coerce', then invalid parsing will be set as NaT
        - If 'ignore', then invalid parsing will return the input
    format : string, default None
        strftime to parse time, eg "%d/%m/%Y", note that "%f" will parse
        all the way up to nanoseconds.
    infer_datetime_format : boolean, default False
        If True and no `format` is given, attempt to infer the format of the
        datetime strings, and if it can be inferred, switch to a faster
        method of parsing them. In some cases this can increase the parsing
        speed by ~5-10x.

    Returns
    -------
    ret : datetime if parsing succeeded.
        Return type depends on input:

        - list-like: DatetimeIndex
        - Series: Series of datetime64 dtype
        - scalar: Timestamp

        In case when it is not possible to return designated types (e.g. when
        any element of input is before Timestamp.min or after Timestamp.max)
        return will have datetime.datetime type (or corresponding
        array/Series).

    Examples
    --------
    Assembling a datetime from multiple columns of a DataFrame. The keys can be
    common abbreviations like ['year', 'month', 'day', 'minute', 'second',
    'ms', 'us', 'ns']) or plurals of the same

    >>> df = ks.DataFrame({'year': [2015, 2016],
    ...                    'month': [2, 3],
    ...                    'day': [4, 5]})
    >>> ks.to_datetime(df)
    0   2015-02-04
    1   2016-03-05
    Name: _to_datetime2(arg_day=day, arg_month=month, arg_year=year), dtype: datetime64[ns]

    If a date does not meet the `timestamp limitations
    <http://pandas.pydata.org/pandas-docs/stable/timeseries.html
    #timeseries-timestamp-limits>`_, passing errors='ignore'
    will return the original input instead of raising any exception.

    Passing errors='coerce' will force an out-of-bounds date to NaT,
    in addition to forcing non-dates (or non-parseable dates) to NaT.

    >>> ks.to_datetime('13000101', format='%Y%m%d', errors='ignore')
    datetime.datetime(1300, 1, 1, 0, 0)
    >>> ks.to_datetime('13000101', format='%Y%m%d', errors='coerce')
    NaT

    Passing infer_datetime_format=True can often-times speedup a parsing
    if its not an ISO8601 format exactly, but in a regular format.

    >>> s = ks.Series(['3/11/2000', '3/12/2000', '3/13/2000'] * 1000)
    >>> s.head()
    0    3/11/2000
    1    3/12/2000
    2    3/13/2000
    3    3/11/2000
    4    3/12/2000
    Name: 0, dtype: object

    >>> import timeit
    >>> timeit.timeit(
    ...    lambda: repr(ks.to_datetime(s, infer_datetime_format=True)),
    ...    number = 1)  # doctest: +SKIP
    0.35832712500000063

    >>> timeit.timeit(
    ...    lambda: repr(ks.to_datetime(s, infer_datetime_format=False)),
    ...    number = 1)  # doctest: +SKIP
    0.8895321660000004
    """
    if isinstance(arg, Series):
        return _to_datetime1(
            arg,
            errors=errors,
            format=format,
            infer_datetime_format=infer_datetime_format)
    if isinstance(arg, DataFrame):
        return _to_datetime2(
            arg_year=arg['year'],
            arg_month=arg['month'],
            arg_day=arg['day'],
            errors=errors,
            format=format,
            infer_datetime_format=infer_datetime_format)
    if isinstance(arg, dict):
        return _to_datetime2(
            arg_year=arg['year'],
            arg_month=arg['month'],
            arg_day=arg['day'],
            errors=errors,
            format=format,
            infer_datetime_format=infer_datetime_format)
    return pd.to_datetime(
        arg, errors=errors, format=format, infer_datetime_format=infer_datetime_format)


def get_dummies(data, prefix=None, prefix_sep='_', dummy_na=False, columns=None, sparse=False,
                drop_first=False, dtype=None):
    """
    Convert categorical variable into dummy/indicator variables, also
    known as one hot encoding.

    Parameters
    ----------
    data : array-like, Series, or DataFrame
    prefix : string, list of strings, or dict of strings, default None
        String to append DataFrame column names.
        Pass a list with length equal to the number of columns
        when calling get_dummies on a DataFrame. Alternatively, `prefix`
        can be a dictionary mapping column names to prefixes.
    prefix_sep : string, default '_'
        If appending prefix, separator/delimiter to use. Or pass a
        list or dictionary as with `prefix.`
    dummy_na : bool, default False
        Add a column to indicate NaNs, if False NaNs are ignored.
    columns : list-like, default None
        Column names in the DataFrame to be encoded.
        If `columns` is None then all the columns with
        `object` or `category` dtype will be converted.
    sparse : bool, default False
        Whether the dummy-encoded columns should be be backed by
        a :class:`SparseArray` (True) or a regular NumPy array (False).
        In Koalas, this value must be "False".
    drop_first : bool, default False
        Whether to get k-1 dummies out of k categorical levels by removing the
        first level.
    dtype : dtype, default np.uint8
        Data type for new columns. Only a single dtype is allowed.

    Returns
    -------
    dummies : DataFrame

    See Also
    --------
    Series.str.get_dummies

    Examples
    --------
    >>> s = ks.Series(list('abca'))

    >>> ks.get_dummies(s)
       a  b  c
    0  1  0  0
    1  0  1  0
    2  0  0  1
    3  1  0  0

    >>> df = ks.DataFrame({'A': ['a', 'b', 'a'], 'B': ['b', 'a', 'c'],
    ...                    'C': [1, 2, 3]},
    ...                   columns=['A', 'B', 'C'])

    >>> ks.get_dummies(df, prefix=['col1', 'col2'])
       C  col1_a  col1_b  col2_a  col2_b  col2_c
    0  1       1       0       0       1       0
    1  2       0       1       1       0       0
    2  3       1       0       0       0       1

    >>> ks.get_dummies(ks.Series(list('abcaa')))
       a  b  c
    0  1  0  0
    1  0  1  0
    2  0  0  1
    3  1  0  0
    4  1  0  0

    >>> ks.get_dummies(ks.Series(list('abcaa')), drop_first=True)
       b  c
    0  0  0
    1  1  0
    2  0  1
    3  0  0
    4  0  0

    >>> ks.get_dummies(ks.Series(list('abc')), dtype=float)
         a    b    c
    0  1.0  0.0  0.0
    1  0.0  1.0  0.0
    2  0.0  0.0  1.0
    """
    if sparse is not False:
        raise NotImplementedError("get_dummies currently does not support sparse")

    if isinstance(columns, str):
        columns = [columns]
    if dtype is None:
        dtype = 'byte'

    if isinstance(data, Series):
        if prefix is not None:
            prefix = [str(prefix)]
        columns = [data.name]
        kdf = data.to_dataframe()
        remaining_columns = []
    else:
        if isinstance(prefix, str):
            raise ValueError("get_dummies currently does not support prefix as string types")
        kdf = data.copy()
        if columns is None:
            columns = [column for column in kdf.columns
                       if isinstance(data._sdf.schema[column].dataType,
                                     _get_dummies_default_accept_types)]
        if len(columns) == 0:
            return kdf

        if prefix is None:
            prefix = columns

        column_set = set(columns)
        remaining_columns = [kdf[column] for column in kdf.columns if column not in column_set]

    if any(not isinstance(kdf._sdf.schema[column].dataType, _get_dummies_acceptable_types)
           for column in columns):
        raise ValueError("get_dummies currently only accept {} values"
                         .format(', '.join([t.typeName() for t in _get_dummies_acceptable_types])))

    if prefix is not None and len(columns) != len(prefix):
        raise ValueError(
            "Length of 'prefix' ({}) did not match the length of the columns being encoded ({})."
            .format(len(prefix), len(columns)))

    all_values = _reduce_spark_multi(kdf._sdf, [F.collect_set(F.col(column)).alias(column)
                                                for column in columns])
    for i, column in enumerate(columns):
        values = sorted(all_values[i])
        if drop_first:
            values = values[1:]

        def column_name(value):
            if prefix is None:
                return str(value)
            else:
                return '{}{}{}'.format(prefix[i], prefix_sep, value)

        for value in values:
            remaining_columns.append((kdf[column].notnull() & (kdf[column] == value))
                                     .astype(dtype)
                                     .rename(column_name(value)))
        if dummy_na:
            remaining_columns.append(kdf[column].isnull().astype(dtype).rename(column_name('nan')))

    return kdf[remaining_columns]


# TODO: there are many parameters to implement and support. See Pandas's pd.concat.
def concat(objs, axis=0, join='outer', ignore_index=False):
    """
    Concatenate pandas objects along a particular axis with optional set logic
    along the other axes.

    Parameters
    ----------
    objs : a sequence of Series or DataFrame
        Any None objects will be dropped silently unless
        they are all None in which case a ValueError will be raised
    axis : {0/'index'}, default 0
        The axis to concatenate along.
    join : {'inner', 'outer'}, default 'outer'
        How to handle indexes on other axis(es)
    ignore_index : boolean, default False
        If True, do not use the index values along the concatenation axis. The
        resulting axis will be labeled 0, ..., n - 1. This is useful if you are
        concatenating objects where the concatenation axis does not have
        meaningful indexing information. Note the index values on the other
        axes are still respected in the join.

    Returns
    -------
    concatenated : object, type of objs
        When concatenating all ``Series`` along the index (axis=0), a
        ``Series`` is returned. When ``objs`` contains at least one
        ``DataFrame``, a ``DataFrame`` is returned.

    See Also
    --------
    DataFrame.merge

    Examples
    --------
    Combine two ``Series``.

    >>> s1 = ks.Series(['a', 'b'])
    >>> s2 = ks.Series(['c', 'd'])
    >>> ks.concat([s1, s2])
    0    a
    1    b
    0    c
    1    d
    Name: 0, dtype: object

    Clear the existing index and reset it in the result
    by setting the ``ignore_index`` option to ``True``.

    >>> ks.concat([s1, s2], ignore_index=True)
    0    a
    1    b
    2    c
    3    d
    Name: 0, dtype: object

    Combine two ``DataFrame`` objects with identical columns.

    >>> df1 = ks.DataFrame([['a', 1], ['b', 2]],
    ...                    columns=['letter', 'number'])
    >>> df1
      letter  number
    0      a       1
    1      b       2
    >>> df2 = ks.DataFrame([['c', 3], ['d', 4]],
    ...                    columns=['letter', 'number'])
    >>> df2
      letter  number
    0      c       3
    1      d       4

    >>> ks.concat([df1, df2])
      letter  number
    0      a       1
    1      b       2
    0      c       3
    1      d       4

    Combine ``DataFrame`` and ``Series`` objects with different columns.

    >>> ks.concat([df2, s1, s2])
          0 letter  number
    0  None      c     3.0
    1  None      d     4.0
    0     a   None     NaN
    1     b   None     NaN
    0     c   None     NaN
    1     d   None     NaN

    Combine ``DataFrame`` objects with overlapping columns
    and return everything. Columns outside the intersection will
    be filled with ``None`` values.

    >>> df3 = ks.DataFrame([['c', 3, 'cat'], ['d', 4, 'dog']],
    ...                    columns=['letter', 'number', 'animal'])
    >>> df3
      letter  number animal
    0      c       3    cat
    1      d       4    dog

    >>> ks.concat([df1, df3])
      animal letter  number
    0   None      a       1
    1   None      b       2
    0    cat      c       3
    1    dog      d       4

    Combine ``DataFrame`` objects with overlapping columns
    and return only those that are shared by passing ``inner`` to
    the ``join`` keyword argument.

    >>> ks.concat([df1, df3], join="inner")
      letter  number
    0      a       1
    1      b       2
    0      c       3
    1      d       4
    """
    if not isinstance(objs, (dict, Iterable)):
        raise TypeError('first argument must be an iterable of koalas '
                        'objects, you passed an object of type '
                        '"{name}"'.format(name=type(objs).__name__))

    if axis not in [0, 'index']:
        raise ValueError('axis should be either 0 or "index" currently.')

    if all(map(lambda obj: obj is None, objs)):
        raise ValueError("All objects passed were None")
    objs = list(filter(lambda obj: obj is not None, objs))

    for obj in objs:
        if not isinstance(obj, (Series, DataFrame)):
            raise TypeError('cannot concatenate object of type '"'{name}"'; only ks.Series '
                            'and ks.DataFrame are valid'.format(name=type(objs).__name__))

    # Series, Series ...
    # We should return Series if objects are all Series.
    should_return_series = all(map(lambda obj: isinstance(obj, Series), objs))

    # DataFrame, Series ... & Series, Series ...
    # In this case, we should return DataFrame.
    new_objs = []
    for obj in objs:
        if isinstance(obj, Series):
            obj = obj.to_dataframe()
        new_objs.append(obj)
    objs = new_objs

    # DataFrame, DataFrame, ...
    # All Series are converted into DataFrame and then compute concat.
    if not ignore_index:
        indices_of_kdfs = [kdf._metadata.index_map for kdf in objs]
        index_of_first_kdf = indices_of_kdfs[0]
        for index_of_kdf in indices_of_kdfs:
            if index_of_first_kdf != index_of_kdf:
                raise ValueError(
                    'Index type and names should be same in the objects to concatenate. '
                    'You passed different indices '
                    '{index_of_first_kdf} and {index_of_kdf}'.format(
                        index_of_first_kdf=index_of_first_kdf, index_of_kdf=index_of_kdf))

    columns_of_kdfs = [kdf._metadata.columns for kdf in objs]
    first_kdf = objs[0]
    if ignore_index:
        columns_of_first_kdf = first_kdf._metadata.data_columns
    else:
        columns_of_first_kdf = first_kdf._metadata.columns
    if all(current_kdf == columns_of_first_kdf for current_kdf in columns_of_kdfs):
        # If all columns are in the same order and values, use it.
        kdfs = objs
    else:
        if ignore_index:
            columns_to_apply = [kdf._metadata.data_columns for kdf in objs]
        else:
            columns_to_apply = [kdf._metadata.columns for kdf in objs]

        if join == "inner":
            interested_columns = set.intersection(*map(set, columns_to_apply))
            # Keep the column order with its firsts DataFrame.
            interested_columns = list(map(
                lambda c: columns_of_first_kdf[columns_of_first_kdf.index(c)],
                interested_columns))

            kdfs = []
            for kdf in objs:
                sdf = kdf._sdf.select(interested_columns)
                if ignore_index:
                    kdfs.append(DataFrame(sdf))
                else:
                    kdfs.append(DataFrame(sdf, first_kdf._metadata.copy()))
        elif join == "outer":
            # If there are columns unmatched, just sort the column names.
            merged_columns = set(
                itertools.chain.from_iterable(columns_to_apply))

            kdfs = []
            for kdf in objs:
                if ignore_index:
                    columns_to_add = merged_columns - set(kdf._metadata.data_columns)
                else:
                    columns_to_add = merged_columns - set(kdf._metadata.columns)

                # TODO: NaN and None difference for missing values. pandas seems filling NaN.
                kdf = kdf.assign(**dict(zip(columns_to_add, [None] * len(columns_to_add))))

                if ignore_index:
                    sdf = kdf._sdf.select(sorted(kdf._metadata.data_columns))
                else:
                    sdf = kdf._sdf.select(
                        kdf._metadata.index_columns + sorted(kdf._metadata.data_columns))

                kdf = DataFrame(sdf, kdf._metadata.copy(
                    data_columns=sorted(kdf._metadata.data_columns)))
                kdfs.append(kdf)
        else:
            raise ValueError(
                "Only can inner (intersect) or outer (union) join the other axis.")

    concatenated = kdfs[0]._sdf
    for kdf in kdfs[1:]:
        concatenated = concatenated.unionByName(kdf._sdf)

    if ignore_index:
        result_kdf = DataFrame(concatenated.select(kdfs[0]._metadata.data_columns))
    else:
        result_kdf = DataFrame(concatenated, kdfs[0]._metadata.copy())

    if should_return_series:
        # If all input were Series, we should return Series.
        return _col(result_kdf)
    else:
        return result_kdf


# @pandas_wraps(return_col=np.datetime64)
@pandas_wraps
def _to_datetime1(arg, errors, format, infer_datetime_format) -> Col[np.datetime64]:
    return pd.to_datetime(
        arg,
        errors=errors,
        format=format,
        infer_datetime_format=infer_datetime_format)


# @pandas_wraps(return_col=np.datetime64)
@pandas_wraps
def _to_datetime2(arg_year, arg_month, arg_day,
                  errors, format, infer_datetime_format) -> Col[np.datetime64]:
    arg = dict(year=arg_year, month=arg_month, day=arg_day)
    for key in arg:
        if arg[key] is None:
            del arg[key]
    return pd.to_datetime(
        arg,
        errors=errors,
        format=format,
        infer_datetime_format=infer_datetime_format)


_get_dummies_default_accept_types = (
    DecimalType, StringType, DateType
)
_get_dummies_acceptable_types = _get_dummies_default_accept_types + (
    ByteType, ShortType, IntegerType, LongType, FloatType, DoubleType, BooleanType, TimestampType
)
