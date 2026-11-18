from oa_agent.executor.invoke_args import unwrap_bag_args


def test_unwrap_params_for_one_by_params():
    assert unwrap_bag_args("one_by_params", {"params": {"a": 1}, "page": 2}) == {"a": 1, "page": 2}


def test_top_level_wins():
    assert unwrap_bag_args("page_list", {"params": {"limit": 99}, "limit": 5}) == {"limit": 5}


def test_named_args_unchanged():
    args = {"params": {"a": 1}, "userId": "x"}
    assert unwrap_bag_args("named_args", args) == args
