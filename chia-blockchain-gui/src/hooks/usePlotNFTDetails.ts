import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import type PlotNFT from '../types/PlotNFT';
import type Plot from '../types/Plot';
import PlotNFTState from '../constants/PlotNFTState';
import type { RootState } from '../modules/rootReducer';
import usePlots from './usePlots';
import usePlotNFTName from './usePlotNFTName';

import useCurrencyCode from './useCurrencyCode';
import toBech32m from '../util/toBech32m';
import { bech32m } from 'bech32';



export default function usePlotNFTDetails(nft: PlotNFT): {
  isPending: boolean;
  state: PlotNFTState;
  walletId: number;
  isSynced: boolean;
  balance?: number;
  humanName: string;
  plots?: Plot[];
  canEdit: boolean;
  isSelfPooling: boolean;
} {
  const isWalletSynced = useSelector(
    (state: RootState) => state.wallet_state.status.synced,
  );

  function isAddress(stringToCheck: string): boolean {
    try {
      bech32m.decode(stringToCheck);
      return true;
    } catch (err) {
      return false;
    }
  }

  function getHex(stringToCheck: string): string {
    if  (isAddress(stringToCheck) === true){
      const decodedAddress = bech32m.decode(stringToCheck);
      return Buffer.from(bech32m.fromWords(decodedAddress.words)).toString('hex');
    }
    return "None"
  }


  const { plots } = usePlots();
  const cCode = useCurrencyCode();
  const humanName = usePlotNFTName(nft);

  const details = useMemo(() => {
    const {
      pool_state: {
        p2_singleton_puzzle_hash,
        pool_config: { p2_chia_contract_or_pool_public_key },
      },
      pool_wallet_status: {
        current: { state },
        target,
        wallet_id,
      },
      wallet_balance: { confirmed_wallet_balance },
    } = nft;
    const poolContractPuzzleHash = `0x${p2_singleton_puzzle_hash}`;
    const isPending = !!target && target.state !== state;
    const isLeavingPool = state === PlotNFTState.LEAVING_POOL;
    const isSelfPooling = state === PlotNFTState.SELF_POOLING;
    const hexString = "0x" + getHex(p2_chia_contract_or_pool_public_key)
    return {
      isPending,
      state,
      walletId: wallet_id,
      isSynced: isWalletSynced,
      balance: confirmed_wallet_balance,
      canEdit: isWalletSynced && (!isPending || isLeavingPool),
      humanName,
      isSelfPooling,
      plots:
        plots &&
        plots.filter(
          (plot) => plot.pool_contract_puzzle_hash === poolContractPuzzleHash || plot.pool_public_key === p2_chia_contract_or_pool_public_key || plot.pool_contract_puzzle_hash === hexString,
        ),
    };
  }, [nft, isWalletSynced, plots, humanName]);

  return details;
}
