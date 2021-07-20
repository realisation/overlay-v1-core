// SPDX-License-Identifier: MIT
pragma solidity ^0.8.2;

import "@openzeppelin/contracts/utils/math/Math.sol";

import "./FixedPoint.sol";

library PositionV2 {
    using FixedPoint for FixedPoint.uq112x112;
    using FixedPoint for FixedPoint.uq144x112;

    uint constant RESOLUTION = 1e4;

    struct Info {
        address market; // the market for the position
        bool isLong; // whether long or short
        uint leverage; // discrete initial leverage amount
        uint pricePoint; // pricePointIndex
        uint256 oiShares; // shares of total open interest on long/short side, depending on isLong value
        uint256 debt; // total debt associated with this position
        uint256 cost; // total amount of collateral initially locked; effectively, cost to enter position
    }

    function _openInterest(
        Info memory _self,
        uint256 totalOi,
        uint256 totalOiShares
    ) private pure returns (uint256 oi) {
        return _self.oiShares * totalOi / totalOiShares;
    }

    /// @dev Floors to zero, so won't properly compute if self is underwater
    function _value(
        Info memory _self,
        uint256 totalOi,
        uint256 totalOiShares,
        uint256 priceFrame
    ) private pure returns (uint256 val) {
        uint256 oi = _openInterest(_self, totalOi, totalOiShares);
        if (_self.isLong) {
            // oi * priceFrame - debt
            val = oi * priceFrame;
            val -= Math.min(_self.debt, val); // floor to 0
        } else {
            // oi * (2 - priceFrame) - debt
            val = oi * 2;
            val -= Math.min(oi * priceFrame + _self.debt, val); // floor to 0
        }
    }

    /// @dev is true when position value < 0
    function _isUnderwater(
        Info memory _self,
        uint256 totalOi,
        uint256 totalOiShares,
        uint256 priceFrame
    ) private pure returns (bool isUnder) {
        uint256 oi = _openInterest(_self, totalOi, totalOiShares);
        if (_self.isLong) {
            isUnder = (oi * priceFrame < _self.debt);
        } else {
            isUnder = (oi * 2 < _self.debt + oi * priceFrame);
        }
    }

    /// @dev Floors to _self.debt, so won't properly compute if _self is underwater
    function _notional(
        Info memory _self,
        uint256 totalOi,
        uint256 totalOiShares,
        uint256 priceFrame
    ) private pure returns (uint256 notion) {
        uint256 val = _value(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        );
        notion = val + _self.debt;
    }

    /// @dev ceils FixedPoint.uq144x112(uint256.max) if position value <= 0
    function _openLeverage(
        Info memory _self,
        uint256 totalOi,
        uint256 totalOiShares,
        uint256 priceFrame
    ) private pure returns (FixedPoint.uq144x112 memory lev) {
        // TODO: Fix for https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/utils/math/SafeCast.sol#L9
        // cast to uint112 given FixedPoint division by val
        uint112 val = uint112(_value(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        ));
        if (val == 0) {
            lev = FixedPoint.uq144x112(type(uint256).max);
        } else {
            uint256 notion = _notional(
                _self,
                totalOi,
                totalOiShares,
                priceFrame
            );
            lev = FixedPoint.uq144x112(notion).div(val);
        }
    }

    /// @dev floors zero if position value <= 0; equiv to 1 / open leverage
    function _openMargin(
        Info memory _self,
        uint256 totalOi,
        uint256 totalOiShares,
        uint256 priceFrame
    ) private pure returns (FixedPoint.uq144x112 memory margin) {
        // cast to uint112 given FixedPoint division by notion
        uint112 notion = uint112(_notional(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        ));
        if (notion == 0) margin = FixedPoint.uq144x112(0);
        else {
            uint256 val = _value(
                _self,
                totalOi,
                totalOiShares,
                priceFrame
            );
            margin = FixedPoint.uq144x112(val).div(notion);
        }
    }

    /// @dev is true when open margin < maintenance margin
    function _isLiquidatable(
        Info memory _self,
        uint256 totalOi,
        uint256 totalOiShares,
        uint256 priceFrame,
        uint256 marginMaintenance
    ) private pure returns (bool can) {

        uint256 positionValue = _value(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        );

        FixedPoint.uq144x112 memory maintenance = FixedPoint
            .encode144(uint144(marginMaintenance))
            .div(uint112(RESOLUTION))
            .div(uint112(_self.leverage));

        can = FixedPoint.encode144(uint144(positionValue)).lt(maintenance);

    }

    /// @notice Computes the open interest of a position
    function openInterest(
        Info storage self,
        uint256 totalOi,
        uint256 totalOiShares
    ) internal view returns (uint256) {

        Info memory _self = self;

        return _openInterest(_self, totalOi, totalOiShares);

    }

    /// @notice Computes the value of a position
    /// @dev Floors to zero, so won't properly compute if self is underwater
    function value(
        Info storage self,
        uint256 priceFrame,
        uint256 totalOi,
        uint256 totalOiShares
    ) internal view returns (uint256) {

        Info memory _self = self;

        return _value(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        );

    }

    /// @notice Whether position is underwater
    /// @dev is true when position value <= 0
    function isUnderwater(
        Info storage self,
        uint256 priceFrame,
        uint256 totalOi,
        uint256 totalOiShares
    ) internal view returns (bool) {

        Info memory _self = self;

        return _isUnderwater(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        );

    }

    /// @notice Computes the notional of a position
    /// @dev Floors to _self.debt, so won't properly compute if _self is underwater
    function notional(
        Info storage self,
        uint256 priceFrame,
        uint256 totalOi,
        uint256 totalOiShares
    ) internal view returns (uint256) {

        Info memory _self = self;

        return _notional(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        );

    }

    /// @notice Computes the open leverage of a position
    /// @dev ceils FixedPoint.uq144x112(uint256.max) if position value <= 0
    function openLeverage(
        Info storage self,
        uint256 priceFrame,
        uint256 totalOi,
        uint256 totalOiShares
    ) internal view returns (FixedPoint.uq144x112 memory) {

        Info memory _self = self;

        return _openLeverage(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        );

    }

    /// @notice Computes the open margin of a position
    /// @dev floors zero if position value <= 0; equiv to 1 / open leverage
    function openMargin(
        Info storage self,
        uint256 priceFrame,
        uint256 totalOi,
        uint256 totalOiShares
    ) internal view returns (FixedPoint.uq144x112 memory) {

        Info memory _self = self;

        return _openMargin(
            _self,
            totalOi,
            totalOiShares,
            priceFrame
        );

    }

    /// @notice Whether a position can be liquidated
    /// @dev is true when open margin < maintenance margin
    function isLiquidatable(
        Info storage self,
        uint256 priceFrame,
        uint256 totalOi,
        uint256 totalOiShares,
        uint256 marginMaintenance
    ) internal view returns (bool) {

        Info memory _self = self;

        return _isLiquidatable(
            _self,
            totalOi,
            totalOiShares,
            priceFrame,
            marginMaintenance
        );

    }

    /// @notice Computes the liquidation price of a position
    /// @dev TODO: ... function liquidationPrice()
}
