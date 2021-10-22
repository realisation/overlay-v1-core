import brownie
import math
from brownie.test import given, strategy
from pytest import approx, mark


def print_logs(tx):
    for i in range(len(tx.events['log'])):
        print(tx.events['log'][i]['k'] + ": " + str(tx.events['log'][i]['v']))


MIN_COLLATERAL = 1e14  # min amount to build
TOKEN_DECIMALS = 18
TOKEN_TOTAL_SUPPLY = 8000000
OI_CAP = 800000e18
FEE_RESOLUTION = 1e18
PRICES = [
    {
        "entry": {
            "timestamp": 1633520012,
            "micro_price": 307964236479616,
            "macro_price": 308748518420310,
            "rtol": 1e-4,
        }
    },
    {
        "entry": {
            "timestamp": 1633504052,
            "micro_price": 317828920167667,
            "macro_price": 316765033525492,
            "rtol": 1e-4,
        }
    },
    {
        "entry": {
            "timestamp": 1633554032,
            "micro_price": 326752400804053,
            "macro_price": 326749496496389,
            "rtol": 1e-4,
        }
    },
]


@given(
    collateral=strategy('uint256', min_value=1e18,
                        max_value=(OI_CAP - 1e4)/100),
    leverage=strategy('uint8', min_value=1, max_value=100),
    is_long=strategy('bool'))
def test_build_success_zero_impact(
        ovl_collateral,
        token,
        mothership,
        market,
        bob,
        rewards,
        collateral,
        leverage,
        is_long
        ):

    oi = collateral * leverage
    trade_fee = oi * mothership.fee() / FEE_RESOLUTION

    # get prior state of collateral manager
    fee_bucket = ovl_collateral.fees()
    ovl_balance = token.balanceOf(ovl_collateral)

    # get prior state of market
    market_oi = market.oiLong() if is_long else market.oiShort()

    # approve collateral contract to spend bob's ovl to build position
    token.approve(ovl_collateral, collateral, {"from": bob})

    # build the position
    tx = ovl_collateral.build(
        market, collateral, leverage, is_long, {"from": bob})

    assert 'Build' in tx.events
    assert 'positionId' in tx.events['Build']
    pid = tx.events['Build']['positionId']

    # fees should be sent to fee bucket in collateral manager
    assert int(fee_bucket + trade_fee) == approx(ovl_collateral.fees())

    # check collateral sent to collateral manager
    assert int(ovl_balance + collateral) \
        == approx(token.balanceOf(ovl_collateral))

    # check position token issued with correct oi shares
    collateral_adjusted = collateral - trade_fee
    oi_adjusted = collateral_adjusted * leverage
    assert approx(ovl_collateral.balanceOf(bob, pid)) == int(oi_adjusted)

    # check position attributes for PID
    (pos_market,
     pos_islong,
     pos_lev,
     pos_price_idx,
     pos_oishares,
     pos_debt,
     pos_cost) = ovl_collateral.positions(pid)

    assert pos_market == market
    assert pos_islong == is_long
    assert pos_lev == leverage
    assert pos_price_idx == market.pricePointCurrentIndex()
    assert approx(pos_oishares) == int(oi_adjusted)
    assert approx(pos_debt) == int(oi_adjusted - collateral_adjusted)
    assert approx(pos_cost) == int(collateral_adjusted)

    # check oi has been added on the market for respective side of trade
    if is_long:
        assert int(market_oi + oi_adjusted) == approx(market.oiLong())
    else:
        assert int(market_oi + oi_adjusted) == approx(market.oiShort())


def test_build_when_market_not_supported(
            ovl_collateral,
            token,
            mothership,
            market,
            notamarket,
            bob,
            leverage=1,  # doesn't matter
            is_long=True  # doesn't matter
        ):

    EXPECTED_ERROR_MESSAGE = 'OVLV1:!market'

    token.approve(ovl_collateral, 3e18, {"from": bob})
    # just to avoid failing min_collateral check because of fees
    trade_amt = MIN_COLLATERAL*2

    assert mothership.marketActive(market)
    assert not mothership.marketActive(notamarket)
    with brownie.reverts(EXPECTED_ERROR_MESSAGE):
        ovl_collateral.build(notamarket, trade_amt,
                             leverage, is_long, {'from': bob})


@given(
    leverage=strategy('uint8', min_value=1, max_value=100),
    is_long=strategy('bool')
    )
def test_build_min_collateral(
            ovl_collateral,
            token,
            mothership,
            market,
            bob,
            leverage,
            is_long
        ):

    EXPECTED_ERROR_MESSAGE = 'OVLV1:collat<min'

    token.approve(ovl_collateral, 3e18, {"from": bob})

    # Here we compute exactly how much to trade in order to have just the
    # MIN_COLLATERAL after fees are taken
    # TODO: check this logic ...
    FL = mothership.fee()*leverage
    fee_offset = MIN_COLLATERAL*(FL/(FEE_RESOLUTION - FL))
    trade_amt = (MIN_COLLATERAL + fee_offset)

    # higher than min collateral passes
    tx = ovl_collateral.build(market, trade_amt + 1,
                              leverage, is_long, {'from': bob})
    assert isinstance(tx, brownie.network.transaction.TransactionReceipt)

    # lower than min collateral fails
    with brownie.reverts(EXPECTED_ERROR_MESSAGE):
        ovl_collateral.build(market, trade_amt - 2,
                             leverage, is_long, {'from': bob})


def test_build_max_leverage(
            ovl_collateral,
            token,
            market,
            bob,
            collateral=1e18,
            is_long=True
        ):

    EXPECTED_ERROR_MESSAGE = 'OVLV1:lev>max'

    token.approve(ovl_collateral, collateral, {"from": bob})
    # just to avoid failing min_collateral check because of fees
    trade_amt = MIN_COLLATERAL*2

    tx = ovl_collateral.build(
        market, trade_amt, ovl_collateral.maxLeverage(market), is_long, {'from': bob})
    assert isinstance(tx, brownie.network.transaction.TransactionReceipt)

    with brownie.reverts(EXPECTED_ERROR_MESSAGE):
        ovl_collateral.build(market, trade_amt, ovl_collateral.maxLeverage(market) + 1,
                             is_long, {'from': bob})


def test_build_cap(
            token,
            ovl_collateral,
            market,
            bob,
            leverage=1,
            is_long=True
        ):

    # NOTE error msg should be 'OVLV1:collat>cap'
    EXPECTED_ERROR_MESSAGE = 'OVLV1:>cap'

    cap = market.oiCap()
    token.approve(ovl_collateral, cap*2, {"from": bob})

    tx = ovl_collateral.build(market, cap, leverage, is_long, {'from': bob})
    assert isinstance(tx, brownie.network.transaction.TransactionReceipt)

    with brownie.reverts(EXPECTED_ERROR_MESSAGE):
        ovl_collateral.build(market, cap + 1, leverage, is_long, {"from": bob})


@given(
    collateral=strategy('uint256', min_value=1e18,
                        max_value=(OI_CAP - 1e4)/100),
    leverage=strategy('uint8', min_value=1, max_value=100),
    is_long=strategy('bool')
    )
def test_oi_added(
            ovl_collateral,
            token,
            mothership,
            market,
            bob,
            collateral,
            leverage,
            is_long
        ):

    market_oi = market.oiLong() if is_long else market.oiShort()
    assert market_oi == 0

    token.approve(ovl_collateral, collateral, {"from": bob})
    tx = ovl_collateral.build(
        market, collateral, leverage, is_long, {"from": bob})

    oi = collateral * leverage
    trade_fee = oi * mothership.fee() / FEE_RESOLUTION

    # added oi less fees should be taken from collateral
    collateral_adjusted = collateral - trade_fee
    oi_adjusted = collateral_adjusted * leverage

    new_market_oi = market.oiLong() if is_long else market.oiShort()
    assert approx(new_market_oi) == int(oi_adjusted)


@given(
    # bc we build multiple positions w leverage take care not to hit CAP
    collateral=strategy('uint256', min_value=1e18,
                        max_value=(OI_CAP - 1e4)/300),
    leverage=strategy('uint8', min_value=1, max_value=100),
    is_long=strategy('bool')
    )
@mark.parametrize('price', PRICES)
def test_entry_update_price_fetching(
            ovl_collateral,
            token,
            market,
            bob,
            collateral,
            leverage,
            is_long,
            price
        ):

    token.approve(ovl_collateral, collateral*3, {"from": bob})

    market_idx = market.pricePointCurrentIndex()

    # Mine to the entry time then build
    brownie.chain.mine(timestamp=price["entry"]["timestamp"])

    _ = ovl_collateral.build(
        market, collateral, leverage, is_long, {"from": bob})
    idx1 = market.pricePointCurrentIndex()
    assert market_idx == idx1

    entry_bid1, entry_ask1, entry_price1 = market.pricePoints(idx1)
    assert price["entry"]["macro_price"] == \
        approx(entry_price1, rel=price["entry"]["rtol"])

    # make sure bid/ask calculated correctly
    spread = market.pbnj()/1e18
    bid = math.exp(-spread)*min(price["entry"]["micro_price"],
                                price["entry"]["macro_price"])
    ask = math.exp(spread) * max(price["entry"]["micro_price"],
                                 price["entry"]["macro_price"])
    assert bid == approx(entry_bid1, rel=price["entry"]["rtol"])
    assert ask == approx(entry_ask1, rel=price["entry"]["rtol"])

    brownie.chain.mine(timedelta=market.compoundingPeriod()+1)

    _ = ovl_collateral.build(
        market, collateral, leverage, is_long, {"from": bob})
    idx2 = market.pricePointCurrentIndex()

    assert idx2 == idx1+1

    entry_bid2, entry_ask2, entry_price2 = market.pricePoints(idx2)
    assert entry_price2 != price["entry"]["macro_price"]


@given(
    # bc we build multiple positions w leverage take care not to hit CAP
    collateral=strategy('uint256', min_value=1e18,
                        max_value=(OI_CAP - 1e4)/300),
    leverage=strategy('uint8', min_value=1, max_value=100),
    is_long=strategy('bool'),
    compoundings=strategy('uint16', min_value=1, max_value=36),
    )
def test_entry_update_compounding_oi_onesided(
            ovl_collateral,
            token,
            market,
            mothership,
            bob,
            collateral,
            leverage,
            is_long,
            compoundings
        ):

    token.approve(ovl_collateral, collateral*2, {"from": bob})
    _ = ovl_collateral.build(
        market, collateral, leverage, is_long, {"from": bob})

    _ = ovl_collateral.build(
        market, collateral, leverage, is_long, {"from": bob})
    oi2 = market.oiLong() if is_long else market.oiShort()

    oi = collateral * leverage
    trade_fee = oi * mothership.fee() / FEE_RESOLUTION

    collateral_adjusted = collateral - trade_fee
    oi_adjusted = collateral_adjusted * leverage
    assert approx(oi2) == int(2*oi_adjusted)

    brownie.chain.mine(timedelta=compoundings*market.compoundingPeriod()+1)
    _ = market.update({"from": bob})

    oi_after_funding = market.oiLong() if is_long else market.oiShort()

    k = market.k() / 1e18
    funding_factor = (1 - 2*k)**(compoundings)
    expected_oi = oi2 * funding_factor

    assert int(expected_oi) == approx(oi_after_funding)


@given(
    # bc we build multiple positions w leverage take care not to hit CAP
    collateral=strategy('uint256', min_value=1e18,
                        max_value=(OI_CAP - 1e4)/300),
    leverage=strategy('uint8', min_value=1, max_value=100),
    is_long=strategy('bool'),
    compoundings=strategy('uint16', min_value=1, max_value=36),
    )
def test_entry_update_compounding_oi_imbalance(
            ovl_collateral,
            token,
            market,
            mothership,
            alice,
            bob,
            collateral,
            leverage,
            is_long,
            compoundings
        ):

    # transfer alice some tokens first given the conftest
    token.transfer(alice, collateral, {"from": bob})

    token.approve(ovl_collateral, collateral, {"from": alice})
    token.approve(ovl_collateral, 2*collateral, {"from": bob})

    _ = ovl_collateral.build(
        market, collateral, leverage, not is_long, {"from": alice})
    _ = ovl_collateral.build(
        market, 2*collateral, leverage, is_long, {"from": bob})

    market_oi_long = market.oiLong()
    market_oi_short = market.oiShort()

    collateral_adjusted = collateral - collateral * \
        leverage*mothership.fee()/FEE_RESOLUTION
    oi_adjusted = collateral_adjusted*leverage

    if is_long:
        assert approx(market_oi_long) == int(2*oi_adjusted)
        assert approx(market_oi_short) == int(oi_adjusted)
    else:
        assert approx(market_oi_long) == int(oi_adjusted)
        assert approx(market_oi_short) == int(2*oi_adjusted)

    market_oi_imbalance = market_oi_long - market_oi_short

    brownie.chain.mine(timedelta=compoundings*market.compoundingPeriod()+1)
    _ = market.update({"from": bob})

    oi_long_after_funding = market.oiLong()
    oi_short_after_funding = market.oiShort()
    oi_imbalance_after_funding = oi_long_after_funding - oi_short_after_funding

    k = market.k() / 1e18
    funding_factor = (1 - 2*k)**(compoundings)
    expected_oi_imbalance = market_oi_imbalance * funding_factor

    assert int(expected_oi_imbalance) == approx(oi_imbalance_after_funding)
    assert int(market_oi_long + market_oi_short) == approx(
        oi_long_after_funding + oi_short_after_funding)
