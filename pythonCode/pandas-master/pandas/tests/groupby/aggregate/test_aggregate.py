"""
test .agg behavior / note that .apply is tested generally in test_groupby.py
"""
import datetime
import functools
from functools import partial
import re

import numpy as np
import pytest

from pandas.errors import PerformanceWarning

from pandas.core.dtypes.common import is_integer_dtype

import pandas as pd
from pandas import (
    DataFrame,
    Index,
    MultiIndex,
    Series,
    concat,
)
import pandas._testing as tm
from pandas.core.base import SpecificationError
from pandas.core.groupby.grouper import Grouping


def test_groupby_agg_no_extra_calls():
    # GH#31760
    df = DataFrame({"key": ["a", "b", "c", "c"], "value": [1, 2, 3, 4]})
    gb = df.groupby("key")["value"]

    def dummy_func(x):
        assert len(x) != 0
        return x.sum()

    gb.agg(dummy_func)


def test_agg_regression1(tsframe):
    grouped = tsframe.groupby([lambda x: x.year, lambda x: x.month])
    result = grouped.agg(np.mean)
    expected = grouped.mean()
    tm.assert_frame_equal(result, expected)


def test_agg_must_agg(df):
    grouped = df.groupby("A")["C"]

    msg = "Must produce aggregated value"
    with pytest.raises(Exception, match=msg):
        grouped.agg(lambda x: x.describe())
    with pytest.raises(Exception, match=msg):
        grouped.agg(lambda x: x.index[:2])


def test_agg_ser_multi_key(df):
    # TODO(wesm): unused
    ser = df.C  # noqa

    f = lambda x: x.sum()
    results = df.C.groupby([df.A, df.B]).aggregate(f)
    expected = df.groupby(["A", "B"]).sum()["C"]
    tm.assert_series_equal(results, expected)


def test_groupby_aggregation_mixed_dtype():

    # GH 6212
    expected = DataFrame(
        {
            "v1": [5, 5, 7, np.nan, 3, 3, 4, 1],
            "v2": [55, 55, 77, np.nan, 33, 33, 44, 11],
        },
        index=MultiIndex.from_tuples(
            [
                (1, 95),
                (1, 99),
                (2, 95),
                (2, 99),
                ("big", "damp"),
                ("blue", "dry"),
                ("red", "red"),
                ("red", "wet"),
            ],
            names=["by1", "by2"],
        ),
    )

    df = DataFrame(
        {
            "v1": [1, 3, 5, 7, 8, 3, 5, np.nan, 4, 5, 7, 9],
            "v2": [11, 33, 55, 77, 88, 33, 55, np.nan, 44, 55, 77, 99],
            "by1": ["red", "blue", 1, 2, np.nan, "big", 1, 2, "red", 1, np.nan, 12],
            "by2": [
                "wet",
                "dry",
                99,
                95,
                np.nan,
                "damp",
                95,
                99,
                "red",
                99,
                np.nan,
                np.nan,
            ],
        }
    )

    g = df.groupby(["by1", "by2"])
    result = g[["v1", "v2"]].mean()
    tm.assert_frame_equal(result, expected)


def test_groupby_aggregation_multi_level_column():
    # GH 29772
    lst = [
        [True, True, True, False],
        [True, False, np.nan, False],
        [True, True, np.nan, False],
        [True, True, np.nan, False],
    ]
    df = DataFrame(
        data=lst,
        columns=MultiIndex.from_tuples([("A", 0), ("A", 1), ("B", 0), ("B", 1)]),
    )

    result = df.groupby(level=1, axis=1).sum()
    expected = DataFrame({0: [2.0, 1, 1, 1], 1: [1, 0, 1, 1]})

    tm.assert_frame_equal(result, expected)


def test_agg_apply_corner(ts, tsframe):
    # nothing to group, all NA
    grouped = ts.groupby(ts * np.nan)
    assert ts.dtype == np.float64

    # groupby float64 values results in Float64Index
    exp = Series([], dtype=np.float64, index=Index([], dtype=np.float64))
    tm.assert_series_equal(grouped.sum(), exp)
    tm.assert_series_equal(grouped.agg(np.sum), exp)
    tm.assert_series_equal(grouped.apply(np.sum), exp, check_index_type=False)

    # DataFrame
    grouped = tsframe.groupby(tsframe["A"] * np.nan)
    exp_df = DataFrame(
        columns=tsframe.columns,
        dtype=float,
        index=Index([], name="A", dtype=np.float64),
    )
    tm.assert_frame_equal(grouped.sum(), exp_df)
    tm.assert_frame_equal(grouped.agg(np.sum), exp_df)
    tm.assert_frame_equal(grouped.apply(np.sum), exp_df)


def test_agg_grouping_is_list_tuple(ts):
    df = tm.makeTimeDataFrame()

    grouped = df.groupby(lambda x: x.year)
    grouper = grouped.grouper.groupings[0].grouper
    grouped.grouper.groupings[0] = Grouping(ts.index, list(grouper))

    result = grouped.agg(np.mean)
    expected = grouped.mean()
    tm.assert_frame_equal(result, expected)

    grouped.grouper.groupings[0] = Grouping(ts.index, tuple(grouper))

    result = grouped.agg(np.mean)
    expected = grouped.mean()
    tm.assert_frame_equal(result, expected)


def test_agg_python_multiindex(mframe):
    grouped = mframe.groupby(["A", "B"])

    result = grouped.agg(np.mean)
    expected = grouped.mean()
    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize(
    "groupbyfunc", [lambda x: x.weekday(), [lambda x: x.month, lambda x: x.weekday()]]
)
def test_aggregate_str_func(tsframe, groupbyfunc):
    grouped = tsframe.groupby(groupbyfunc)

    # single series
    result = grouped["A"].agg("std")
    expected = grouped["A"].std()
    tm.assert_series_equal(result, expected)

    # group frame by function name
    result = grouped.aggregate("var")
    expected = grouped.var()
    tm.assert_frame_equal(result, expected)

    # group frame by function dict
    result = grouped.agg({"A": "var", "B": "std", "C": "mean", "D": "sem"})
    expected = DataFrame(
        {
            "A": grouped["A"].var(),
            "B": grouped["B"].std(),
            "C": grouped["C"].mean(),
            "D": grouped["D"].sem(),
        }
    )
    tm.assert_frame_equal(result, expected)


def test_agg_str_with_kwarg_axis_1_raises(df, reduction_func):
    gb = df.groupby(level=0)
    if reduction_func in ("idxmax", "idxmin"):
        error = TypeError
        msg = "reduction operation '.*' not allowed for this dtype"
    else:
        error = ValueError
        msg = f"Operation {reduction_func} does not support axis=1"
    with pytest.raises(error, match=msg):
        gb.agg(reduction_func, axis=1)


def test_aggregate_item_by_item(df):
    grouped = df.groupby("A")

    aggfun = lambda ser: ser.size
    result = grouped.agg(aggfun)
    foo = (df.A == "foo").sum()
    bar = (df.A == "bar").sum()
    K = len(result.columns)

    # GH5782
    exp = Series(np.array([foo] * K), index=list("BCD"), name="foo")
    tm.assert_series_equal(result.xs("foo"), exp)

    exp = Series(np.array([bar] * K), index=list("BCD"), name="bar")
    tm.assert_almost_equal(result.xs("bar"), exp)

    def aggfun(ser):
        return ser.size

    result = DataFrame().groupby(df.A).agg(aggfun)
    assert isinstance(result, DataFrame)
    assert len(result) == 0


def test_wrap_agg_out(three_group):
    grouped = three_group.groupby(["A", "B"])

    def func(ser):
        if ser.dtype == object:
            raise TypeError
        else:
            return ser.sum()

    result = grouped.aggregate(func)
    exp_grouped = three_group.loc[:, three_group.columns != "C"]
    expected = exp_grouped.groupby(["A", "B"]).aggregate(func)
    tm.assert_frame_equal(result, expected)


def test_agg_multiple_functions_maintain_order(df):
    # GH #610
    funcs = [("mean", np.mean), ("max", np.max), ("min", np.min)]
    result = df.groupby("A")["C"].agg(funcs)
    exp_cols = Index(["mean", "max", "min"])

    tm.assert_index_equal(result.columns, exp_cols)


def test_agg_multiple_functions_same_name():
    # GH 30880
    df = DataFrame(
        np.random.randn(1000, 3),
        index=pd.date_range("1/1/2012", freq="S", periods=1000),
        columns=["A", "B", "C"],
    )
    result = df.resample("3T").agg(
        {"A": [partial(np.quantile, q=0.9999), partial(np.quantile, q=0.1111)]}
    )
    expected_index = pd.date_range("1/1/2012", freq="3T", periods=6)
    expected_columns = MultiIndex.from_tuples([("A", "quantile"), ("A", "quantile")])
    expected_values = np.array(
        [df.resample("3T").A.quantile(q=q).values for q in [0.9999, 0.1111]]
    ).T
    expected = DataFrame(
        expected_values, columns=expected_columns, index=expected_index
    )
    tm.assert_frame_equal(result, expected)


def test_agg_multiple_functions_same_name_with_ohlc_present():
    # GH 30880
    # ohlc expands dimensions, so different test to the above is required.
    df = DataFrame(
        np.random.randn(1000, 3),
        index=pd.date_range("1/1/2012", freq="S", periods=1000),
        columns=["A", "B", "C"],
    )
    result = df.resample("3T").agg(
        {"A": ["ohlc", partial(np.quantile, q=0.9999), partial(np.quantile, q=0.1111)]}
    )
    expected_index = pd.date_range("1/1/2012", freq="3T", periods=6)
    expected_columns = MultiIndex.from_tuples(
        [
            ("A", "ohlc", "open"),
            ("A", "ohlc", "high"),
            ("A", "ohlc", "low"),
            ("A", "ohlc", "close"),
            ("A", "quantile", "A"),
            ("A", "quantile", "A"),
        ]
    )
    non_ohlc_expected_values = np.array(
        [df.resample("3T").A.quantile(q=q).values for q in [0.9999, 0.1111]]
    ).T
    expected_values = np.hstack([df.resample("3T").A.ohlc(), non_ohlc_expected_values])
    expected = DataFrame(
        expected_values, columns=expected_columns, index=expected_index
    )
    # PerformanceWarning is thrown by `assert col in right` in assert_frame_equal
    with tm.assert_produces_warning(PerformanceWarning):
        tm.assert_frame_equal(result, expected)


def test_multiple_functions_tuples_and_non_tuples(df):
    # #1359
    funcs = [("foo", "mean"), "std"]
    ex_funcs = [("foo", "mean"), ("std", "std")]

    result = df.groupby("A")["C"].agg(funcs)
    expected = df.groupby("A")["C"].agg(ex_funcs)
    tm.assert_frame_equal(result, expected)

    result = df.groupby("A").agg(funcs)
    expected = df.groupby("A").agg(ex_funcs)
    tm.assert_frame_equal(result, expected)


def test_more_flexible_frame_multi_function(df):
    grouped = df.groupby("A")

    exmean = grouped.agg({"C": np.mean, "D": np.mean})
    exstd = grouped.agg({"C": np.std, "D": np.std})

    expected = concat([exmean, exstd], keys=["mean", "std"], axis=1)
    expected = expected.swaplevel(0, 1, axis=1).sort_index(level=0, axis=1)

    d = {"C": [np.mean, np.std], "D": [np.mean, np.std]}
    result = grouped.aggregate(d)

    tm.assert_frame_equal(result, expected)

    # be careful
    result = grouped.aggregate({"C": np.mean, "D": [np.mean, np.std]})
    expected = grouped.aggregate({"C": np.mean, "D": [np.mean, np.std]})
    tm.assert_frame_equal(result, expected)

    def foo(x):
        return np.mean(x)

    def bar(x):
        return np.std(x, ddof=1)

    # this uses column selection & renaming
    msg = r"nested renamer is not supported"
    with pytest.raises(SpecificationError, match=msg):
        d = {"C": np.mean, "D": {"foo": np.mean, "bar": np.std}}
        grouped.aggregate(d)

    # But without renaming, these functions are OK
    d = {"C": [np.mean], "D": [foo, bar]}
    grouped.aggregate(d)


def test_multi_function_flexible_mix(df):
    # GH #1268
    grouped = df.groupby("A")

    # Expected
    d = {"C": {"foo": "mean", "bar": "std"}, "D": {"sum": "sum"}}
    # this uses column selection & renaming
    msg = r"nested renamer is not supported"
    with pytest.raises(SpecificationError, match=msg):
        grouped.aggregate(d)

    # Test 1
    d = {"C": {"foo": "mean", "bar": "std"}, "D": "sum"}
    # this uses column selection & renaming
    with pytest.raises(SpecificationError, match=msg):
        grouped.aggregate(d)

    # Test 2
    d = {"C": {"foo": "mean", "bar": "std"}, "D": "sum"}
    # this uses column selection & renaming
    with pytest.raises(SpecificationError, match=msg):
        grouped.aggregate(d)


def test_groupby_agg_coercing_bools():
    # issue 14873
    dat = DataFrame({"a": [1, 1, 2, 2], "b": [0, 1, 2, 3], "c": [None, None, 1, 1]})
    gp = dat.groupby("a")

    index = Index([1, 2], name="a")

    result = gp["b"].aggregate(lambda x: (x != 0).all())
    expected = Series([False, True], index=index, name="b")
    tm.assert_series_equal(result, expected)

    result = gp["c"].aggregate(lambda x: x.isnull().all())
    expected = Series([True, False], index=index, name="c")
    tm.assert_series_equal(result, expected)


@pytest.mark.parametrize(
    "op",
    [
        lambda x: x.sum(),
        lambda x: x.cumsum(),
        lambda x: x.transform("sum"),
        lambda x: x.transform("cumsum"),
        lambda x: x.agg("sum"),
        lambda x: x.agg("cumsum"),
    ],
)
def test_bool_agg_dtype(op):
    # GH 7001
    # Bool sum aggregations result in int
    df = DataFrame({"a": [1, 1], "b": [False, True]})
    s = df.set_index("a")["b"]

    result = op(df.groupby("a"))["b"].dtype
    assert is_integer_dtype(result)

    result = op(s.groupby("a")).dtype
    assert is_integer_dtype(result)


@pytest.mark.parametrize(
    "keys, agg_index",
    [
        (["a"], Index([1], name="a")),
        (["a", "b"], MultiIndex([[1], [2]], [[0], [0]], names=["a", "b"])),
    ],
)
@pytest.mark.parametrize(
    "input_dtype", ["bool", "int32", "int64", "float32", "float64"]
)
@pytest.mark.parametrize(
    "result_dtype", ["bool", "int32", "int64", "float32", "float64"]
)
@pytest.mark.parametrize("method", ["apply", "aggregate", "transform"])
def test_callable_result_dtype_frame(
    keys, agg_index, input_dtype, result_dtype, method
):
    # GH 21240
    df = DataFrame({"a": [1], "b": [2], "c": [True]})
    df["c"] = df["c"].astype(input_dtype)
    op = getattr(df.groupby(keys)[["c"]], method)
    result = op(lambda x: x.astype(result_dtype).iloc[0])
    expected_index = pd.RangeIndex(0, 1) if method == "transform" else agg_index
    expected = DataFrame({"c": [df["c"].iloc[0]]}, index=expected_index).astype(
        result_dtype
    )
    if method == "apply":
        expected.columns.names = [0]
    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize(
    "keys, agg_index",
    [
        (["a"], Index([1], name="a")),
        (["a", "b"], MultiIndex([[1], [2]], [[0], [0]], names=["a", "b"])),
    ],
)
@pytest.mark.parametrize("input", [True, 1, 1.0])
@pytest.mark.parametrize("dtype", [bool, int, float])
@pytest.mark.parametrize("method", ["apply", "aggregate", "transform"])
def test_callable_result_dtype_series(keys, agg_index, input, dtype, method):
    # GH 21240
    df = DataFrame({"a": [1], "b": [2], "c": [input]})
    op = getattr(df.groupby(keys)["c"], method)
    result = op(lambda x: x.astype(dtype).iloc[0])
    expected_index = pd.RangeIndex(0, 1) if method == "transform" else agg_index
    expected = Series([df["c"].iloc[0]], index=expected_index, name="c").astype(dtype)
    tm.assert_series_equal(result, expected)


def test_order_aggregate_multiple_funcs():
    # GH 25692
    df = DataFrame({"A": [1, 1, 2, 2], "B": [1, 2, 3, 4]})

    res = df.groupby("A").agg(["sum", "max", "mean", "ohlc", "min"])
    result = res.columns.levels[1]

    expected = Index(["sum", "max", "mean", "ohlc", "min"])

    tm.assert_index_equal(result, expected)


@pytest.mark.parametrize("dtype", [np.int64, np.uint64])
@pytest.mark.parametrize("how", ["first", "last", "min", "max", "mean", "median"])
def test_uint64_type_handling(dtype, how):
    # GH 26310
    df = DataFrame({"x": 6903052872240755750, "y": [1, 2]})
    expected = df.groupby("y").agg({"x": how})
    df.x = df.x.astype(dtype)
    result = df.groupby("y").agg({"x": how})
    result.x = result.x.astype(np.int64)
    tm.assert_frame_equal(result, expected, check_exact=True)


def test_func_duplicates_raises():
    # GH28426
    msg = "Function names"
    df = DataFrame({"A": [0, 0, 1, 1], "B": [1, 2, 3, 4]})
    with pytest.raises(SpecificationError, match=msg):
        df.groupby("A").agg(["min", "min"])


@pytest.mark.parametrize(
    "index",
    [
        pd.CategoricalIndex(list("abc")),
        pd.interval_range(0, 3),
        pd.period_range("2020", periods=3, freq="D"),
        MultiIndex.from_tuples([("a", 0), ("a", 1), ("b", 0)]),
    ],
)
def test_agg_index_has_complex_internals(index):
    # GH 31223
    df = DataFrame({"group": [1, 1, 2], "value": [0, 1, 0]}, index=index)
    result = df.groupby("group").agg({"value": Series.nunique})
    expected = DataFrame({"group": [1, 2], "value": [2, 1]}).set_index("group")
    tm.assert_frame_equal(result, expected)


def test_agg_split_block():
    # https://github.com/pandas-dev/pandas/issues/31522
    df = DataFrame(
        {
            "key1": ["a", "a", "b", "b", "a"],
            "key2": ["one", "two", "one", "two", "one"],
            "key3": ["three", "three", "three", "six", "six"],
        }
    )
    result = df.groupby("key1").min()
    expected = DataFrame(
        {"key2": ["one", "one"], "key3": ["six", "six"]},
        index=Index(["a", "b"], name="key1"),
    )
    tm.assert_frame_equal(result, expected)


def test_agg_split_object_part_datetime():
    # https://github.com/pandas-dev/pandas/pull/31616
    df = DataFrame(
        {
            "A": pd.date_range("2000", periods=4),
            "B": ["a", "b", "c", "d"],
            "C": [1, 2, 3, 4],
            "D": ["b", "c", "d", "e"],
            "E": pd.date_range("2000", periods=4),
            "F": [1, 2, 3, 4],
        }
    ).astype(object)
    result = df.groupby([0, 0, 0, 0]).min()
    expected = DataFrame(
        {
            "A": [pd.Timestamp("2000")],
            "B": ["a"],
            "C": [1],
            "D": ["b"],
            "E": [pd.Timestamp("2000")],
            "F": [1],
        }
    )
    tm.assert_frame_equal(result, expected)


class TestNamedAggregationSeries:
    def test_series_named_agg(self):
        df = Series([1, 2, 3, 4])
        gr = df.groupby([0, 0, 1, 1])
        result = gr.agg(a="sum", b="min")
        expected = DataFrame(
            {"a": [3, 7], "b": [1, 3]}, columns=["a", "b"], index=[0, 1]
        )
        tm.assert_frame_equal(result, expected)

        result = gr.agg(b="min", a="sum")
        expected = expected[["b", "a"]]
        tm.assert_frame_equal(result, expected)

    def test_no_args_raises(self):
        gr = Series([1, 2]).groupby([0, 1])
        with pytest.raises(TypeError, match="Must provide"):
            gr.agg()

        # but we do allow this
        result = gr.agg([])
        expected = DataFrame()
        tm.assert_frame_equal(result, expected)

    def test_series_named_agg_duplicates_no_raises(self):
        # GH28426
        gr = Series([1, 2, 3]).groupby([0, 0, 1])
        grouped = gr.agg(a="sum", b="sum")
        expected = DataFrame({"a": [3, 3], "b": [3, 3]})
        tm.assert_frame_equal(expected, grouped)

    def test_mangled(self):
        gr = Series([1, 2, 3]).groupby([0, 0, 1])
        result = gr.agg(a=lambda x: 0, b=lambda x: 1)
        expected = DataFrame({"a": [0, 0], "b": [1, 1]})
        tm.assert_frame_equal(result, expected)

    @pytest.mark.parametrize(
        "inp",
        [
            pd.NamedAgg(column="anything", aggfunc="min"),
            ("anything", "min"),
            ["anything", "min"],
        ],
    )
    def test_named_agg_nametuple(self, inp):
        # GH34422
        s = Series([1, 1, 2, 2, 3, 3, 4, 5])
        msg = f"func is expected but received {type(inp).__name__}"
        with pytest.raises(TypeError, match=msg):
            s.groupby(s.values).agg(a=inp)


class TestNamedAggregationDataFrame:
    def test_agg_relabel(self):
        df = DataFrame(
            {"group": ["a", "a", "b", "b"], "A": [0, 1, 2, 3], "B": [5, 6, 7, 8]}
        )
        result = df.groupby("group").agg(a_max=("A", "max"), b_max=("B", "max"))
        expected = DataFrame(
            {"a_max": [1, 3], "b_max": [6, 8]},
            index=Index(["a", "b"], name="group"),
            columns=["a_max", "b_max"],
        )
        tm.assert_frame_equal(result, expected)

        # order invariance
        p98 = functools.partial(np.percentile, q=98)
        result = df.groupby("group").agg(
            b_min=("B", "min"),
            a_min=("A", min),
            a_mean=("A", np.mean),
            a_max=("A", "max"),
            b_max=("B", "max"),
            a_98=("A", p98),
        )
        expected = DataFrame(
            {
                "b_min": [5, 7],
                "a_min": [0, 2],
                "a_mean": [0.5, 2.5],
                "a_max": [1, 3],
                "b_max": [6, 8],
                "a_98": [0.98, 2.98],
            },
            index=Index(["a", "b"], name="group"),
            columns=["b_min", "a_min", "a_mean", "a_max", "b_max", "a_98"],
        )
        tm.assert_frame_equal(result, expected)

    def test_agg_relabel_non_identifier(self):
        df = DataFrame(
            {"group": ["a", "a", "b", "b"], "A": [0, 1, 2, 3], "B": [5, 6, 7, 8]}
        )

        result = df.groupby("group").agg(**{"my col": ("A", "max")})
        expected = DataFrame({"my col": [1, 3]}, index=Index(["a", "b"], name="group"))
        tm.assert_frame_equal(result, expected)

    def test_duplicate_no_raises(self):
        # GH 28426, if use same input function on same column,
        # no error should raise
        df = DataFrame({"A": [0, 0, 1, 1], "B": [1, 2, 3, 4]})

        grouped = df.groupby("A").agg(a=("B", "min"), b=("B", "min"))
        expected = DataFrame({"a": [1, 3], "b": [1, 3]}, index=Index([0, 1], name="A"))
        tm.assert_frame_equal(grouped, expected)

        quant50 = functools.partial(np.percentile, q=50)
        quant70 = functools.partial(np.percentile, q=70)
        quant50.__name__ = "quant50"
        quant70.__name__ = "quant70"

        test = DataFrame({"col1": ["a", "a", "b", "b", "b"], "col2": [1, 2, 3, 4, 5]})

        grouped = test.groupby("col1").agg(
            quantile_50=("col2", quant50), quantile_70=("col2", quant70)
        )
        expected = DataFrame(
            {"quantile_50": [1.5, 4.0], "quantile_70": [1.7, 4.4]},
            index=Index(["a", "b"], name="col1"),
        )
        tm.assert_frame_equal(grouped, expected)

    def test_agg_relabel_with_level(self):
        df = DataFrame(
            {"A": [0, 0, 1, 1], "B": [1, 2, 3, 4]},
            index=MultiIndex.from_product([["A", "B"], ["a", "b"]]),
        )
        result = df.groupby(level=0).agg(
            aa=("A", "max"), bb=("A", "min"), cc=("B", "mean")
        )
        expected = DataFrame(
            {"aa": [0, 1], "bb": [0, 1], "cc": [1.5, 3.5]}, index=["A", "B"]
        )
        tm.assert_frame_equal(result, expected)

    def test_agg_relabel_other_raises(self):
        df = DataFrame({"A": [0, 0, 1], "B": [1, 2, 3]})
        grouped = df.groupby("A")
        match = "Must provide"
        with pytest.raises(TypeError, match=match):
            grouped.agg(foo=1)

        with pytest.raises(TypeError, match=match):
            grouped.agg()

        with pytest.raises(TypeError, match=match):
            grouped.agg(a=("B", "max"), b=(1, 2, 3))

    def test_missing_raises(self):
        df = DataFrame({"A": [0, 1], "B": [1, 2]})
        match = re.escape("Column(s) ['C'] do not exist")
        with pytest.raises(KeyError, match=match):
            df.groupby("A").agg(c=("C", "sum"))

    def test_agg_namedtuple(self):
        df = DataFrame({"A": [0, 1], "B": [1, 2]})
        result = df.groupby("A").agg(
            b=pd.NamedAgg("B", "sum"), c=pd.NamedAgg(column="B", aggfunc="count")
        )
        expected = df.groupby("A").agg(b=("B", "sum"), c=("B", "count"))
        tm.assert_frame_equal(result, expected)

    def test_mangled(self):
        df = DataFrame({"A": [0, 1], "B": [1, 2], "C": [3, 4]})
        result = df.groupby("A").agg(b=("B", lambda x: 0), c=("C", lambda x: 1))
        expected = DataFrame({"b": [0, 0], "c": [1, 1]}, index=Index([0, 1], name="A"))
        tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize(
    "agg_col1, agg_col2, agg_col3, agg_result1, agg_result2, agg_result3",
    [
        (
            (("y", "A"), "max"),
            (("y", "A"), np.min),
            (("y", "B"), "mean"),
            [1, 3],
            [0, 2],
            [5.5, 7.5],
        ),
        (
            (("y", "A"), lambda x: max(x)),
            (("y", "A"), lambda x: 1),
            (("y", "B"), "mean"),
            [1, 3],
            [1, 1],
            [5.5, 7.5],
        ),
        (
            pd.NamedAgg(("y", "A"), "max"),
            pd.NamedAgg(("y", "B"), np.mean),
            pd.NamedAgg(("y", "A"), lambda x: 1),
            [1, 3],
            [5.5, 7.5],
            [1, 1],
        ),
    ],
)
def test_agg_relabel_multiindex_column(
    agg_col1, agg_col2, agg_col3, agg_result1, agg_result2, agg_result3
):
    # GH 29422, add tests for multiindex column cases
    df = DataFrame(
        {"group": ["a", "a", "b", "b"], "A": [0, 1, 2, 3], "B": [5, 6, 7, 8]}
    )
    df.columns = MultiIndex.from_tuples([("x", "group"), ("y", "A"), ("y", "B")])
    idx = Index(["a", "b"], name=("x", "group"))

    result = df.groupby(("x", "group")).agg(a_max=(("y", "A"), "max"))
    expected = DataFrame({"a_max": [1, 3]}, index=idx)
    tm.assert_frame_equal(result, expected)

    result = df.groupby(("x", "group")).agg(
        col_1=agg_col1, col_2=agg_col2, col_3=agg_col3
    )
    expected = DataFrame(
        {"col_1": agg_result1, "col_2": agg_result2, "col_3": agg_result3}, index=idx
    )
    tm.assert_frame_equal(result, expected)


def test_agg_relabel_multiindex_raises_not_exist():
    # GH 29422, add test for raises scenario when aggregate column does not exist
    df = DataFrame(
        {"group": ["a", "a", "b", "b"], "A": [0, 1, 2, 3], "B": [5, 6, 7, 8]}
    )
    df.columns = MultiIndex.from_tuples([("x", "group"), ("y", "A"), ("y", "B")])

    with pytest.raises(KeyError, match="do not exist"):
        df.groupby(("x", "group")).agg(a=(("Y", "a"), "max"))


def test_agg_relabel_multiindex_duplicates():
    # GH29422, add test for raises scenario when getting duplicates
    # GH28426, after this change, duplicates should also work if the relabelling is
    # different
    df = DataFrame(
        {"group": ["a", "a", "b", "b"], "A": [0, 1, 2, 3], "B": [5, 6, 7, 8]}
    )
    df.columns = MultiIndex.from_tuples([("x", "group"), ("y", "A"), ("y", "B")])

    result = df.groupby(("x", "group")).agg(
        a=(("y", "A"), "min"), b=(("y", "A"), "min")
    )
    idx = Index(["a", "b"], name=("x", "group"))
    expected = DataFrame({"a": [0, 2], "b": [0, 2]}, index=idx)
    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize("kwargs", [{"c": ["min"]}, {"b": [], "c": ["min"]}])
def test_groupby_aggregate_empty_key(kwargs):
    # GH: 32580
    df = DataFrame({"a": [1, 1, 2], "b": [1, 2, 3], "c": [1, 2, 4]})
    result = df.groupby("a").agg(kwargs)
    expected = DataFrame(
        [1, 4],
        index=Index([1, 2], dtype="int64", name="a"),
        columns=MultiIndex.from_tuples([["c", "min"]]),
    )
    tm.assert_frame_equal(result, expected)


def test_groupby_aggregate_empty_key_empty_return():
    # GH: 32580 Check if everything works, when return is empty
    df = DataFrame({"a": [1, 1, 2], "b": [1, 2, 3], "c": [1, 2, 4]})
    result = df.groupby("a").agg({"b": []})
    expected = DataFrame(columns=MultiIndex(levels=[["b"], []], codes=[[], []]))
    tm.assert_frame_equal(result, expected)


def test_grouby_agg_loses_results_with_as_index_false_relabel():
    # GH 32240: When the aggregate function relabels column names and
    # as_index=False is specified, the results are dropped.

    df = DataFrame(
        {"key": ["x", "y", "z", "x", "y", "z"], "val": [1.0, 0.8, 2.0, 3.0, 3.6, 0.75]}
    )

    grouped = df.groupby("key", as_index=False)
    result = grouped.agg(min_val=pd.NamedAgg(column="val", aggfunc="min"))
    expected = DataFrame({"key": ["x", "y", "z"], "min_val": [1.0, 0.8, 0.75]})
    tm.assert_frame_equal(result, expected)


def test_grouby_agg_loses_results_with_as_index_false_relabel_multiindex():
    # GH 32240: When the aggregate function relabels column names and
    # as_index=False is specified, the results are dropped. Check if
    # multiindex is returned in the right order

    df = DataFrame(
        {
            "key": ["x", "y", "x", "y", "x", "x"],
            "key1": ["a", "b", "c", "b", "a", "c"],
            "val": [1.0, 0.8, 2.0, 3.0, 3.6, 0.75],
        }
    )

    grouped = df.groupby(["key", "key1"], as_index=False)
    result = grouped.agg(min_val=pd.NamedAgg(column="val", aggfunc="min"))
    expected = DataFrame(
        {"key": ["x", "x", "y"], "key1": ["a", "c", "b"], "min_val": [1.0, 0.75, 0.8]}
    )
    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize(
    "func", [lambda s: s.mean(), lambda s: np.mean(s), lambda s: np.nanmean(s)]
)
def test_multiindex_custom_func(func):
    # GH 31777
    data = [[1, 4, 2], [5, 7, 1]]
    df = DataFrame(data, columns=MultiIndex.from_arrays([[1, 1, 2], [3, 4, 3]]))
    result = df.groupby(np.array([0, 1])).agg(func)
    expected_dict = {
        (1, 3): {0: 1.0, 1: 5.0},
        (1, 4): {0: 4.0, 1: 7.0},
        (2, 3): {0: 2.0, 1: 1.0},
    }
    expected = DataFrame(expected_dict)
    tm.assert_frame_equal(result, expected)


def myfunc(s):
    return np.percentile(s, q=0.90)


@pytest.mark.parametrize("func", [lambda s: np.percentile(s, q=0.90), myfunc])
def test_lambda_named_agg(func):
    # see gh-28467
    animals = DataFrame(
        {
            "kind": ["cat", "dog", "cat", "dog"],
            "height": [9.1, 6.0, 9.5, 34.0],
            "weight": [7.9, 7.5, 9.9, 198.0],
        }
    )

    result = animals.groupby("kind").agg(
        mean_height=("height", "mean"), perc90=("height", func)
    )
    expected = DataFrame(
        [[9.3, 9.1036], [20.0, 6.252]],
        columns=["mean_height", "perc90"],
        index=Index(["cat", "dog"], name="kind"),
    )

    tm.assert_frame_equal(result, expected)


def test_aggregate_mixed_types():
    # GH 16916
    df = DataFrame(
        data=np.array([0] * 9).reshape(3, 3), columns=list("XYZ"), index=list("abc")
    )
    df["grouping"] = ["group 1", "group 1", 2]
    result = df.groupby("grouping").aggregate(lambda x: x.tolist())
    expected_data = [[[0], [0], [0]], [[0, 0], [0, 0], [0, 0]]]
    expected = DataFrame(
        expected_data,
        index=Index([2, "group 1"], dtype="object", name="grouping"),
        columns=Index(["X", "Y", "Z"], dtype="object"),
    )
    tm.assert_frame_equal(result, expected)


@pytest.mark.xfail(reason="Not implemented;see GH 31256")
def test_aggregate_udf_na_extension_type():
    # https://github.com/pandas-dev/pandas/pull/31359
    # This is currently failing to cast back to Int64Dtype.
    # The presence of the NA causes two problems
    # 1. NA is not an instance of Int64Dtype.type (numpy.int64)
    # 2. The presence of an NA forces object type, so the non-NA values is
    #    a Python int rather than a NumPy int64. Python ints aren't
    #    instances of numpy.int64.
    def aggfunc(x):
        if all(x > 2):
            return 1
        else:
            return pd.NA

    df = DataFrame({"A": pd.array([1, 2, 3])})
    result = df.groupby([1, 1, 2]).agg(aggfunc)
    expected = DataFrame({"A": pd.array([1, pd.NA], dtype="Int64")}, index=[1, 2])
    tm.assert_frame_equal(result, expected)


@pytest.mark.parametrize("func", ["min", "max"])
def test_groupby_aggregate_period_column(func):
    # GH 31471
    groups = [1, 2]
    periods = pd.period_range("2020", periods=2, freq="Y")
    df = DataFrame({"a": groups, "b": periods})

    result = getattr(df.groupby("a")["b"], func)()
    idx = pd.Int64Index([1, 2], name="a")
    expected = Series(periods, index=idx, name="b")

    tm.assert_series_equal(result, expected)


@pytest.mark.parametrize("func", ["min", "max"])
def test_groupby_aggregate_period_frame(func):
    # GH 31471
    groups = [1, 2]
    periods = pd.period_range("2020", periods=2, freq="Y")
    df = DataFrame({"a": groups, "b": periods})

    result = getattr(df.groupby("a"), func)()
    idx = pd.Int64Index([1, 2], name="a")
    expected = DataFrame({"b": periods}, index=idx)

    tm.assert_frame_equal(result, expected)


class TestLambdaMangling:
    def test_basic(self):
        df = DataFrame({"A": [0, 0, 1, 1], "B": [1, 2, 3, 4]})
        result = df.groupby("A").agg({"B": [lambda x: 0, lambda x: 1]})

        expected = DataFrame(
            {("B", "<lambda_0>"): [0, 0], ("B", "<lambda_1>"): [1, 1]},
            index=Index([0, 1], name="A"),
        )
        tm.assert_frame_equal(result, expected)

    def test_mangle_series_groupby(self):
        gr = Series([1, 2, 3, 4]).groupby([0, 0, 1, 1])
        result = gr.agg([lambda x: 0, lambda x: 1])
        expected = DataFrame({"<lambda_0>": [0, 0], "<lambda_1>": [1, 1]})
        tm.assert_frame_equal(result, expected)

    @pytest.mark.xfail(reason="GH-26611. kwargs for multi-agg.")
    def test_with_kwargs(self):
        f1 = lambda x, y, b=1: x.sum() + y + b
        f2 = lambda x, y, b=2: x.sum() + y * b
        result = Series([1, 2]).groupby([0, 0]).agg([f1, f2], 0)
        expected = DataFrame({"<lambda_0>": [4], "<lambda_1>": [6]})
        tm.assert_frame_equal(result, expected)

        result = Series([1, 2]).groupby([0, 0]).agg([f1, f2], 0, b=10)
        expected = DataFrame({"<lambda_0>": [13], "<lambda_1>": [30]})
        tm.assert_frame_equal(result, expected)

    def test_agg_with_one_lambda(self):
        # GH 25719, write tests for DataFrameGroupby.agg with only one lambda
        df = DataFrame(
            {
                "kind": ["cat", "dog", "cat", "dog"],
                "height": [9.1, 6.0, 9.5, 34.0],
                "weight": [7.9, 7.5, 9.9, 198.0],
            }
        )

        columns = ["height_sqr_min", "height_max", "weight_max"]
        expected = DataFrame(
            {
                "height_sqr_min": [82.81, 36.00],
                "height_max": [9.5, 34.0],
                "weight_max": [9.9, 198.0],
            },
            index=Index(["cat", "dog"], name="kind"),
            columns=columns,
        )

        # check pd.NameAgg case
        result1 = df.groupby(by="kind").agg(
            height_sqr_min=pd.NamedAgg(
                column="height", aggfunc=lambda x: np.min(x ** 2)
            ),
            height_max=pd.NamedAgg(column="height", aggfunc="max"),
            weight_max=pd.NamedAgg(column="weight", aggfunc="max"),
        )
        tm.assert_frame_equal(result1, expected)

        # check agg(key=(col, aggfunc)) case
        result2 = df.groupby(by="kind").agg(
            height_sqr_min=("height", lambda x: np.min(x ** 2)),
            height_max=("height", "max"),
            weight_max=("weight", "max"),
        )
        tm.assert_frame_equal(result2, expected)

    def test_agg_multiple_lambda(self):
        # GH25719, test for DataFrameGroupby.agg with multiple lambdas
        # with mixed aggfunc
        df = DataFrame(
            {
                "kind": ["cat", "dog", "cat", "dog"],
                "height": [9.1, 6.0, 9.5, 34.0],
                "weight": [7.9, 7.5, 9.9, 198.0],
            }
        )
        columns = [
            "height_sqr_min",
            "height_max",
            "weight_max",
            "height_max_2",
            "weight_min",
        ]
        expected = DataFrame(
            {
                "height_sqr_min": [82.81, 36.00],
                "height_max": [9.5, 34.0],
                "weight_max": [9.9, 198.0],
                "height_max_2": [9.5, 34.0],
                "weight_min": [7.9, 7.5],
            },
            index=Index(["cat", "dog"], name="kind"),
            columns=columns,
        )

        # check agg(key=(col, aggfunc)) case
        result1 = df.groupby(by="kind").agg(
            height_sqr_min=("height", lambda x: np.min(x ** 2)),
            height_max=("height", "max"),
            weight_max=("weight", "max"),
            height_max_2=("height", lambda x: np.max(x)),
            weight_min=("weight", lambda x: np.min(x)),
        )
        tm.assert_frame_equal(result1, expected)

        # check pd.NamedAgg case
        result2 = df.groupby(by="kind").agg(
            height_sqr_min=pd.NamedAgg(
                column="height", aggfunc=lambda x: np.min(x ** 2)
            ),
            height_max=pd.NamedAgg(column="height", aggfunc="max"),
            weight_max=pd.NamedAgg(column="weight", aggfunc="max"),
            height_max_2=pd.NamedAgg(column="height", aggfunc=lambda x: np.max(x)),
            weight_min=pd.NamedAgg(column="weight", aggfunc=lambda x: np.min(x)),
        )
        tm.assert_frame_equal(result2, expected)


def test_groupby_get_by_index():
    # GH 33439
    df = DataFrame({"A": ["S", "W", "W"], "B": [1.0, 1.0, 2.0]})
    res = df.groupby("A").agg({"B": lambda x: x.get(x.index[-1])})
    expected = DataFrame({"A": ["S", "W"], "B": [1.0, 2.0]}).set_index("A")
    tm.assert_frame_equal(res, expected)


@pytest.mark.parametrize(
    "grp_col_dict, exp_data",
    [
        ({"nr": "min", "cat_ord": "min"}, {"nr": [1, 5], "cat_ord": ["a", "c"]}),
        ({"cat_ord": "min"}, {"cat_ord": ["a", "c"]}),
        ({"nr": "min"}, {"nr": [1, 5]}),
    ],
)
def test_groupby_single_agg_cat_cols(grp_col_dict, exp_data):
    # test single aggregations on ordered categorical cols GHGH27800

    # create the result dataframe
    input_df = DataFrame(
        {
            "nr": [1, 2, 3, 4, 5, 6, 7, 8],
            "cat_ord": list("aabbccdd"),
            "cat": list("aaaabbbb"),
        }
    )

    input_df = input_df.astype({"cat": "category", "cat_ord": "category"})
    input_df["cat_ord"] = input_df["cat_ord"].cat.as_ordered()
    result_df = input_df.groupby("cat").agg(grp_col_dict)

    # create expected dataframe
    cat_index = pd.CategoricalIndex(
        ["a", "b"], categories=["a", "b"], ordered=False, name="cat", dtype="category"
    )

    expected_df = DataFrame(data=exp_data, index=cat_index)

    if "cat_ord" in expected_df:
        # ordered categorical columns should be preserved
        dtype = input_df["cat_ord"].dtype
        expected_df["cat_ord"] = expected_df["cat_ord"].astype(dtype)

    tm.assert_frame_equal(result_df, expected_df)


@pytest.mark.parametrize(
    "grp_col_dict, exp_data",
    [
        ({"nr": ["min", "max"], "cat_ord": "min"}, [(1, 4, "a"), (5, 8, "c")]),
        ({"nr": "min", "cat_ord": ["min", "max"]}, [(1, "a", "b"), (5, "c", "d")]),
        ({"cat_ord": ["min", "max"]}, [("a", "b"), ("c", "d")]),
    ],
)
def test_groupby_combined_aggs_cat_cols(grp_col_dict, exp_data):
    # test combined aggregations on ordered categorical cols GH27800

    # create the result dataframe
    input_df = DataFrame(
        {
            "nr": [1, 2, 3, 4, 5, 6, 7, 8],
            "cat_ord": list("aabbccdd"),
            "cat": list("aaaabbbb"),
        }
    )

    input_df = input_df.astype({"cat": "category", "cat_ord": "category"})
    input_df["cat_ord"] = input_df["cat_ord"].cat.as_ordered()
    result_df = input_df.groupby("cat").agg(grp_col_dict)

    # create expected dataframe
    cat_index = pd.CategoricalIndex(
        ["a", "b"], categories=["a", "b"], ordered=False, name="cat", dtype="category"
    )

    # unpack the grp_col_dict to create the multi-index tuple
    # this tuple will be used to create the expected dataframe index
    multi_index_list = []
    for k, v in grp_col_dict.items():
        if isinstance(v, list):
            for value in v:
                multi_index_list.append([k, value])
        else:
            multi_index_list.append([k, v])
    multi_index = MultiIndex.from_tuples(tuple(multi_index_list))

    expected_df = DataFrame(data=exp_data, columns=multi_index, index=cat_index)
    for col in expected_df.columns:
        if isinstance(col, tuple) and "cat_ord" in col:
            # ordered categorical should be preserved
            expected_df[col] = expected_df[col].astype(input_df["cat_ord"].dtype)

    tm.assert_frame_equal(result_df, expected_df)


def test_nonagg_agg():
    # GH 35490 - Single/Multiple agg of non-agg function give same results
    # TODO: agg should raise for functions that don't aggregate
    df = DataFrame({"a": [1, 1, 2, 2], "b": [1, 2, 2, 1]})
    g = df.groupby("a")

    result = g.agg(["cumsum"])
    result.columns = result.columns.droplevel(-1)
    expected = g.agg("cumsum")

    tm.assert_frame_equal(result, expected)


def test_agg_no_suffix_index():
    # GH36189
    df = DataFrame([[4, 9]] * 3, columns=["A", "B"])
    result = df.agg(["sum", lambda x: x.sum(), lambda x: x.sum()])
    expected = DataFrame(
        {"A": [12, 12, 12], "B": [27, 27, 27]}, index=["sum", "<lambda>", "<lambda>"]
    )
    tm.assert_frame_equal(result, expected)

    # test Series case
    result = df["A"].agg(["sum", lambda x: x.sum(), lambda x: x.sum()])
    expected = Series([12, 12, 12], index=["sum", "<lambda>", "<lambda>"], name="A")
    tm.assert_series_equal(result, expected)


def test_aggregate_datetime_objects():
    # https://github.com/pandas-dev/pandas/issues/36003
    # ensure we don't raise an error but keep object dtype for out-of-bounds
    # datetimes
    df = DataFrame(
        {
            "A": ["X", "Y"],
            "B": [
                datetime.datetime(2005, 1, 1, 10, 30, 23, 540000),
                datetime.datetime(3005, 1, 1, 10, 30, 23, 540000),
            ],
        }
    )
    result = df.groupby("A").B.max()
    expected = df.set_index("A")["B"]
    tm.assert_series_equal(result, expected)


def test_aggregate_numeric_object_dtype():
    # https://github.com/pandas-dev/pandas/issues/39329
    # simplified case: multiple object columns where one is all-NaN
    # -> gets split as the all-NaN is inferred as float
    df = DataFrame(
        {"key": ["A", "A", "B", "B"], "col1": list("abcd"), "col2": [np.nan] * 4},
    ).astype(object)
    result = df.groupby("key").min()
    expected = DataFrame(
        {"key": ["A", "B"], "col1": ["a", "c"], "col2": [np.nan, np.nan]}
    ).set_index("key")
    tm.assert_frame_equal(result, expected)

    # same but with numbers
    df = DataFrame(
        {"key": ["A", "A", "B", "B"], "col1": list("abcd"), "col2": range(4)},
    ).astype(object)
    result = df.groupby("key").min()
    expected = DataFrame(
        {"key": ["A", "B"], "col1": ["a", "c"], "col2": [0, 2]}
    ).set_index("key")
    tm.assert_frame_equal(result, expected)


def test_groupby_index_object_dtype():
    # GH 40014
    df = DataFrame({"c0": ["x", "x", "x"], "c1": ["x", "x", "y"], "p": [0, 1, 2]})
    df.index = df.index.astype("O")
    grouped = df.groupby(["c0", "c1"])
    res = grouped.p.agg(lambda x: all(x > 0))
    # Check that providing a user-defined function in agg()
    # produces the correct index shape when using an object-typed index.
    expected_index = MultiIndex.from_tuples(
        [("x", "x"), ("x", "y")], names=("c0", "c1")
    )
    expected = Series([False, True], index=expected_index, name="p")
    tm.assert_series_equal(res, expected)