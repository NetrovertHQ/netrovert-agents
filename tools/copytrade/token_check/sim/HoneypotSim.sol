// SPDX-License-Identifier: MIT
// Read-only honeypot simulator. Never deployed: injected as code via eth_call state override.
// Buys a tiny amount of TOKEN with wrapped native through one pool, then sells it all back, and reports what happened.
pragma solidity ^0.8.24;

interface IERC20 { function balanceOf(address) external view returns (uint); function transfer(address, uint) external returns (bool); }
interface IWETH { function deposit() external payable; }
interface IV2 { function getReserves() external view returns (uint112, uint112, uint32); function token0() external view returns (address);
                function swap(uint, uint, address, bytes calldata) external; }
interface IV3 { function token0() external view returns (address);
                function swap(address, bool, int256, uint160, bytes calldata) external returns (int256, int256); }

contract HoneypotSim {
    uint160 constant MIN_P = 4295128740; uint160 constant MAX_P = 1461446703 * 1e39 + 4852101032 * 1e29 + 8739381991 * 1e19 + 7348046645 * 1e9 + 987782020;  // TickMath MAX_SQRT_RATIO - 1
    address cbPool; address cbT0; address cbT1;

    // Price limit a few x away from the current price (some forks reject the global min/max bounds with "SPL").
    function lim(address pool, bool zeroForOne) internal view returns (uint160) {
        uint sp;
        (bool ok, bytes memory r) = pool.staticcall(abi.encodeWithSelector(0x3850c7bd));
        if (!ok || r.length < 32) (ok, r) = pool.staticcall(abi.encodeWithSelector(0xe76c01e4));
        if (ok && r.length >= 32) sp = abi.decode(r, (uint256)) & type(uint160).max;
        if (sp == 0) return zeroForOne ? MIN_P : MAX_P;
        if (zeroForOne) { uint d = sp / 4; return d > MIN_P ? uint160(d) : MIN_P; }
        uint u = sp * 4; return u < MAX_P ? uint160(u) : MAX_P;
    }

    // stage: 0 ok, 1 wrap failed, 2 buy reverted, 3 got 0 tokens, 4 transfer probe reverted, 5 sell transfer reverted, 6 sell swap reverted, 7 got 0 back
    function run(address pool, bool v2, address wnative, address token, uint amountIn) external payable
        returns (uint stage, uint buyOut, uint buyGot, uint probeSent, uint probeGot, uint sellSent, uint poolGot, uint sellGot)
    {
        try IWETH(wnative).deposit{value: amountIn}() {} catch { return (1,0,0,0,0,0,0,0); }
        bool t0 = (v2 ? IV2(pool).token0() : IV3(pool).token0()) == token;
        // ---- buy ----
        uint b0 = IERC20(token).balanceOf(address(this));
        if (v2) {
            (uint112 r0, uint112 r1,) = IV2(pool).getReserves();
            (uint rIn, uint rOut) = t0 ? (uint(r1), uint(r0)) : (uint(r0), uint(r1));
            buyOut = amountIn * 990 * rOut / (rIn * 1000 + amountIn * 990);  // assume up to 1% LP fee
            IERC20(wnative).transfer(pool, amountIn);
            try IV2(pool).swap(t0 ? buyOut : 0, t0 ? 0 : buyOut, address(this), "") {} catch { return (2,buyOut,0,0,0,0,0,0); }
        } else {
            cbPool = pool; cbT0 = t0 ? token : wnative; cbT1 = t0 ? wnative : token;
            try IV3(pool).swap(address(this), !t0, int256(amountIn), lim(pool, !t0), "") returns (int256 a0, int256 a1) {
                buyOut = uint(-(t0 ? a0 : a1));
            } catch { return (2,0,0,0,0,0,0,0); }
        }
        buyGot = IERC20(token).balanceOf(address(this)) - b0;
        if (buyGot == 0) return (3,buyOut,0,0,0,0,0,0);
        // ---- transfer probe (1%) to a fresh address: plain transfer tax ----
        address probe = address(uint160(0xbEEF));
        probeSent = buyGot / 100;
        if (probeSent > 0) {
            uint p0 = IERC20(token).balanceOf(probe);
            try IERC20(token).transfer(probe, probeSent) returns (bool) {} catch { return (4,buyOut,buyGot,probeSent,0,0,0,0); }
            probeGot = IERC20(token).balanceOf(probe) - p0;
        }
        // ---- sell everything left ----
        sellSent = IERC20(token).balanceOf(address(this));
        uint w0 = IERC20(wnative).balanceOf(address(this));
        if (v2) {
            uint pb = IERC20(token).balanceOf(pool);
            try IERC20(token).transfer(pool, sellSent) returns (bool) {} catch { return (5,buyOut,buyGot,probeSent,probeGot,sellSent,0,0); }
            poolGot = IERC20(token).balanceOf(pool) - pb;
            (uint112 r0, uint112 r1,) = IV2(pool).getReserves();
            (uint rIn, uint rOut) = t0 ? (uint(r0), uint(r1)) : (uint(r1), uint(r0));
            uint out = poolGot * 990 * rOut / (rIn * 1000 + poolGot * 990);
            try IV2(pool).swap(t0 ? 0 : out, t0 ? out : 0, address(this), "") {} catch { return (6,buyOut,buyGot,probeSent,probeGot,sellSent,poolGot,0); }
        } else {
            uint pb = IERC20(token).balanceOf(pool);
            try IV3(pool).swap(address(this), t0, int256(sellSent), lim(pool, t0), "") {} catch { return (6,buyOut,buyGot,probeSent,probeGot,sellSent,0,0); }
            poolGot = IERC20(token).balanceOf(pool) - pb;
        }
        sellGot = IERC20(wnative).balanceOf(address(this)) - w0;
        stage = sellGot == 0 ? 7 : 0;
    }

    // Any V3-style callback (uniswapV3SwapCallback, algebraSwapCallback, pancakeV3SwapCallback, ramsesV2SwapCallback...): (int256,int256,bytes)
    fallback(bytes calldata data) external payable returns (bytes memory) {
        require(msg.sender == cbPool && data.length >= 68, "cb");
        (int256 d0, int256 d1) = abi.decode(data[4:68], (int256, int256));
        if (d0 > 0) IERC20(cbT0).transfer(msg.sender, uint(d0));
        if (d1 > 0) IERC20(cbT1).transfer(msg.sender, uint(d1));
        return "";
    }
    receive() external payable {}
}
