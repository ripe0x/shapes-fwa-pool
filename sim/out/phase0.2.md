# Phase 0.2 event analysis

Data: FWA, FWAV2Rewards and CollectionFloorOracle logs, blocks 25,944,565 to 26,425,092 (2026-09-10 to 2026-11-16), 2,636,915 logs.

## 1. Volume

Total acquisitions 96,801. First 28 days 2,746/day.
Trailing averages: 1 d 15, 7 d 97.1, 30 d 609.4, 60 d 1565.4 per day.

| week starting | acquisitions/day |
|---|---|
| 2026-09-16 | 3,613.7 |
| 2026-09-23 | 2,837.1 |
| 2026-09-30 | 3,078.3 |
| 2026-10-07 | 1,452.9 |
| 2026-10-14 | 615.1 |
| 2026-10-21 | 593.0 |
| 2026-10-28 | 1,526.7 |
| 2026-11-04 | 51.0 |
| 2026-11-11 | 85.2 |

## 2. Settlement mix

`keep` includes `depositorReclaimBacking`; `bid_eth` includes `depositorReclaimNFT` (same events). Late = settled after the 1 h purchaser window.

### By collection (top 12 by allocations, plus shape packs)

| group | n | bid_eth | bid_tokens | keep | relist | finalize | pending |
|---|---|---|---|---|---|---|---|
| 0x355919971b379ca9741ff29939c4ba716f873560 | 16581 | 69% | 14% | 11% | 5% | 0% | 0% |
| 0xd774557b647330c91bf44cfeab205095f7e6c367 | 13821 | 70% | 12% | 16% | 3% | 0% | 0% |
| 0x6e6b13a7ff06b53dcc3589d35b1b0ffd58c5bdeb | 11021 | 55% | 8% | 35% | 2% | 0% | 0% |
| 0x8fe1a377b83921fe1429adb1b8fbfecd45de9cd8 | 10665 | 64% | 16% | 13% | 7% | 0% | 0% |
| 0x97630aa70ab14ed9883b41dafccbc11349723043 | 8163 | 71% | 17% | 9% | 2% | 0% | 0% |
| 0xc7e67762821b2ed6c0a1f423547b2899822d8650 | 6939 | 69% | 17% | 8% | 6% | 0% | 0% |
| 0x1977f9f8653ffd79fa3198a9c66a0e5efcae02e3 | 4631 | 77% | 13% | 8% | 2% | 0% | 0% |
| 0x790b2cf29ed4f310bf7641f013c65d4560d28371 | 3690 | 80% | 11% | 8% | 2% | 0% | 0% |
| 0x6339e5e072086621540d0362c4e3cea0d643e114 | 2854 | 76% | 11% | 11% | 2% | 0% | 0% |
| 0x4024c2083f5457874ec489f7c7332680bb86c92b | 2314 | 74% | 16% | 6% | 4% | 0% | 0% |
| 0x9378368ba6b85c1fba5b131b530f5f5bedf21a18 | 2109 | 76% | 12% | 10% | 2% | 0% | 0% |
| 0x03b8d129a8f6dc62a797b59aa5eebb11ad63dada | 1522 | 71% | 12% | 14% | 3% | 0% | 0% |
| SHAPE PACKS | 2 | 100% | 0% | 0% | 0% | 0% | 0% |
| all | 91164 | 69% | 13% | 14% | 4% | 0% | 0% |

### By backing / floor ask at allocation (collections with a floor quote)

| group | n | bid_eth | bid_tokens | keep | relist | finalize | pending |
|---|---|---|---|---|---|---|---|
| r 0.00-0.90 | 10913 | 51% | 12% | 33% | 4% | 0% | 0% |
| r 0.90-1.00 | 8650 | 66% | 12% | 17% | 4% | 0% | 0% |
| r 1.00-1.05 | 8988 | 68% | 13% | 15% | 4% | 0% | 0% |
| r 1.05-1.10 | 8664 | 72% | 12% | 12% | 3% | 0% | 0% |
| r 1.10-1.15 | 45984 | 71% | 14% | 11% | 4% | 0% | 0% |
| r 1.15-1.25 | 2039 | 78% | 11% | 11% | 0% | 0% | 0% |
| r 1.25-9.00 | 5866 | 78% | 15% | 7% | 0% | 0% | 0% |

### By purchaser (top 10 by allocations)

| group | n | bid_eth | bid_tokens | keep | relist | finalize | pending |
|---|---|---|---|---|---|---|---|
| 0xcb5ebee4654ce75db2f5c843ccb515988db52b77 | 5212 | 82% | 10% | 8% | 0% | 0% | 0% |
| 0x6330cdfe9ab3b9f9600f61f9ef5c06477bfd8d58 | 3940 | 55% | 8% | 24% | 13% | 0% | 0% |
| 0x184b487d36aea8aa5990569c326c269de246179a | 2561 | 72% | 11% | 17% | 0% | 0% | 0% |
| 0x48aae1669d4cf7988a227b3d68d9d6e9f02840ee | 2372 | 17% | 74% | 8% | 1% | 0% | 0% |
| 0x750a31fa07184caf87b6cce251d2f0d7928badde | 2109 | 97% | 3% | 0% | 0% | 0% | 0% |
| 0x5d802e2fe48392c104ce0401c7eca8a4456f1f16 | 2107 | 92% | 2% | 7% | 0% | 0% | 0% |
| 0x82d16ff1c724ab72f218a3f7f6dd3e5385ee87e8 | 1792 | 73% | 3% | 14% | 9% | 0% | 0% |
| 0xf17017dd78887f7a6d03a81e36ffbdf67eac2b8a | 1634 | 63% | 33% | 3% | 0% | 0% | 0% |
| 0xf7d4cc70520404126ef1eabfe227d8ab8ec22f9f | 1550 | 66% | 2% | 13% | 19% | 0% | 0% |
| 0xbec69dfce4c1fa8b7843fee1ca85788d84a86b06 | 1532 | 25% | 2% | 66% | 6% | 0% | 0% |

Settled after 1 h: 4881 of 91151. Median time to settle: 2.0 min.

## 3. Lifetime fee multiple k

Estimator: fees credited to terminal listings / sum of backing x cumulative selection hazard (weight / totalWeight per acquisition while active). Unbiased under withdrawal censoring; equals k when selection is proportional to weight.

- Reconstructed totalWeight equals the reported value at 96,801 of 96,801 requests.
- Terminal listings 98,308 (active listings excluded from both sides of k).

Selection fairness: selections vs cumulative hazard, all listings, by backing at exit.

| backing ETH | listings | selections | hazard-expected | ratio |
|---|---|---|---|---|
| 0.02-0.03 | 5,997 | 5,562 | 5,905 | 0.942 |
| 0.03-0.04 | 11,585 | 10,393 | 10,554 | 0.985 |
| 0.04-0.06 | 44,042 | 40,408 | 40,068 | 1.008 |
| 0.06-0.1 | 25,359 | 22,734 | 22,628 | 1.005 |
| 0.1-0.3 | 12,468 | 11,230 | 11,179 | 1.005 |
| 0.3-max | 1,441 | 837 | 831 | 1.007 |

- k estimate 1.0418 over the whole history (crown share was 5% for part of it).
- before crown cut to 0.1%: k 1.0414 over 47,074 listings
- after: k 1.0424 over 51,234 listings

| backing ETH | terminal listings | k estimate |
|---|---|---|
| 0-0.03 | 5,179 | 1.0556 |
| 0.03-0.04 | 7,290 | 1.0576 |
| 0.04-0.06 | 20,989 | 1.0384 |
| 0.06-0.1 | 12,724 | 1.0418 |
| 0.1-max | 5,052 | 1.0406 |

(listings that started after the crown cut to 0.1%, block 26,078,548)

- Naive mean fees/backing over allocated listings: 0.9646 (biased low by censoring).
- Conservation: fees credited to all listings 6,530.428 ETH vs distributable 7,126.337 ETH (difference is unclaimed pending fees, crown pot and the retained bid share is excluded).

## 4. Queue lock and exit windows

- Queue non-empty 25.0% of the time.
- Blackouts with a drained queue (usable exit window): 120 of 121.
- Last 30 days: 59 usable of 60; days with zero usable windows: 0.

## 5. ConfigSet timeline (economic keys, changes only)

| block | date | key | value |
|---|---|---|---|
| 25,944,609 | 2026-09-10 | surchargeBps | 500 |
| 25,944,609 | 2026-09-10 | settlementDiscountBps | 9000 |
| 25,944,609 | 2026-09-10 | tokenSettlementDiscountBps | 9250 |
| 25,944,609 | 2026-09-10 | ownerAcquisitionFeeBps | 100 |
| 25,944,609 | 2026-09-10 | ownerSettlementFeeBps | 100 |
| 25,944,609 | 2026-09-10 | settlementWindow | 86400 |
| 25,944,609 | 2026-09-10 | finalizeWindow | 604800 |
| 25,944,609 | 2026-09-10 | minBacking | 10000000000000000 |
| 25,944,609 | 2026-09-10 | maxOracleAge | 604800 |
| 25,944,609 | 2026-09-10 | minOracleChallengePeriod | 21600 |
| 25,944,609 | 2026-09-10 | oracleCeilingPremiumBps | 1000 |
| 25,944,609 | 2026-09-10 | acquisitionsEnabled | 0 |
| 25,944,609 | 2026-09-10 | whitelistEnabled | 1 |
| 25,944,609 | 2026-09-10 | topListingShareBps | 500 |
| 25,944,609 | 2026-09-10 | topThresholdBps | 1000 |
| 25,944,609 | 2026-09-10 | retainedToProtocol | 1 |
| 25,944,615 | 2026-09-10 | topListingShareBps | 50 |
| 25,944,617 | 2026-09-10 | settlementWindow | 0 |
| 25,944,617 | 2026-09-10 | finalizeWindow | 3600 |
| 25,944,617 | 2026-09-10 | settlementWindow | 3600 |
| 25,944,617 | 2026-09-10 | minBacking | 25000000000000000 |
| 25,944,617 | 2026-09-10 | protocolFeeToTokenBps | 10000 |
| 25,944,617 | 2026-09-10 | maxStagedListings | 0 |
| 25,944,618 | 2026-09-10 | acceptBidAsTokensEnabled | 1 |
| 25,991,093 | 2026-09-16 | acquisitionsEnabled | 1 |
| 26,078,548 | 2026-09-28 | topListingShareBps | 10 |
| 26,098,371 | 2026-10-01 | acquisitionsEnabled | 0 |
| 26,098,980 | 2026-10-01 | acquisitionsEnabled | 1 |
| 26,126,279 | 2026-10-05 | acquisitionsEnabled | 0 |
| 26,126,290 | 2026-10-05 | tokenSettlementDiscountBps | 9150 |
| 26,126,292 | 2026-10-05 | acquisitionsEnabled | 1 |
| 26,144,054 | 2026-10-08 | protocolFeeToTokenBps | 8000 |

## 6. Depositor token accrual

Tokens (wei) per sqrt-wei of backing per day, terminal listings with accruals (76,295): median 6.827e+11.

| month ended | listings | median rate | example: 0.0363 ETH listing, tokens/day |
|---|---|---|---|
| 2026-09 | 46199 | 2.381e+12 | 453.7 |
| 2026-10 | 28990 | 2.571e+11 | 48.99 |
| 2026-11 | 1106 | 1.393e+10 | 2.654 |

## 7. Shape packs

Listings 239: #100561 B 0.0360 active, #100562 B 0.0363 active, #100563 B 0.0360 active, #100564 B 0.0363 active, #100565 B 0.0360 active, #100566 B 0.0360 settled/bid_eth, #100577 B 0.0363 active, #100578 B 0.0363 active, #100579 B 0.0363 active, #100580 B 0.0363 active, #100581 B 0.0363 active, #100582 B 0.0363 active, #100583 B 0.0363 active, #100584 B 0.0363 active, #100585 B 0.0363 active, #100586 B 0.0363 active, #100587 B 0.0363 active, #100588 B 0.0363 active, #100589 B 0.0363 active, #100590 B 0.0363 active, #100591 B 0.0363 active, #100592 B 0.0363 active, #100593 B 0.0363 active, #100594 B 0.0363 active, #100595 B 0.0363 active, #100596 B 0.0363 active, #100597 B 0.0363 active, #100598 B 0.0363 active, #100599 B 0.0363 active, #100600 B 0.0363 active, #100601 B 0.0363 active, #100602 B 0.0363 active, #100603 B 0.0363 active, #100604 B 0.0363 active, #100605 B 0.0363 active, #100606 B 0.0363 active, #100607 B 0.0363 active, #100608 B 0.0363 active, #100609 B 0.0363 active, #100610 B 0.0363 active, #100611 B 0.0363 active, #100612 B 0.0363 active, #100613 B 0.0363 active, #100614 B 0.0363 active, #100615 B 0.0363 active, #100616 B 0.0363 active, #100617 B 0.0363 active, #100618 B 0.0363 active, #100619 B 0.0363 active, #100620 B 0.0363 active, #100621 B 0.0363 active, #100622 B 0.0363 active, #100623 B 0.0363 active, #100624 B 0.0363 active, #100625 B 0.0363 active, #100626 B 0.0363 active, #100627 B 0.0363 active, #100628 B 0.0363 active, #100629 B 0.0363 active, #100630 B 0.0363 active, #100631 B 0.0363 active, #100632 B 0.0363 active, #100633 B 0.0363 active, #100634 B 0.0363 active, #100635 B 0.0363 active, #100636 B 0.0363 active, #100637 B 0.0363 active, #100638 B 0.0363 active, #100639 B 0.0363 active, #100640 B 0.0363 active, #100641 B 0.0363 active, #100642 B 0.0363 active, #100643 B 0.0363 active, #100644 B 0.0363 active, #100645 B 0.0363 active, #100646 B 0.0363 active, #100647 B 0.0363 active, #100648 B 0.0363 active, #100649 B 0.0363 active, #100650 B 0.0363 active, #100651 B 0.0363 active, #100652 B 0.0363 active, #100653 B 0.0363 active, #100654 B 0.0363 active, #100655 B 0.0363 active, #100656 B 0.0363 active, #100657 B 0.0363 active, #100658 B 0.0363 active, #100659 B 0.0363 active, #100660 B 0.0363 active, #100661 B 0.0363 active, #100662 B 0.0363 active, #100663 B 0.0363 active, #100664 B 0.0363 active, #100665 B 0.0363 active, #100666 B 0.0363 active, #100667 B 0.0363 active, #100668 B 0.0363 active, #100669 B 0.0363 active, #100670 B 0.0363 active, #100671 B 0.0363 active, #100672 B 0.0363 active, #100673 B 0.0363 active, #100674 B 0.0363 active, #100675 B 0.0363 active, #100676 B 0.0363 active, #100677 B 0.0363 active, #100678 B 0.0363 active, #100679 B 0.0363 active, #100681 B 0.0363 active, #100682 B 0.0363 active, #100683 B 0.0363 active, #100684 B 0.0363 active, #100685 B 0.0363 active, #100686 B 0.0363 active, #100687 B 0.0363 active, #100688 B 0.0363 active, #100689 B 0.0363 active, #100690 B 0.0363 active, #100691 B 0.0363 active, #100692 B 0.0363 active, #100693 B 0.0363 active, #100694 B 0.0363 active, #100695 B 0.0363 active, #100696 B 0.0363 active, #100697 B 0.0363 active, #100698 B 0.0363 active, #100699 B 0.0363 active, #100700 B 0.0363 active, #100702 B 0.0363 active, #100703 B 0.0363 active, #100704 B 0.0363 active, #100705 B 0.0363 active, #100706 B 0.0363 active, #100707 B 0.0363 active, #100708 B 0.0363 active, #100709 B 0.0363 active, #100710 B 0.0363 active, #100711 B 0.0363 active, #100712 B 0.0363 active, #100713 B 0.0363 active, #100714 B 0.0363 active, #100715 B 0.0363 active, #100716 B 0.0363 active, #100717 B 0.0363 active, #100718 B 0.0363 active, #100719 B 0.0363 active, #100720 B 0.0363 active, #100721 B 0.0363 active, #100722 B 0.0363 active, #100723 B 0.0363 active, #100724 B 0.0363 active, #100725 B 0.0363 active, #100726 B 0.0363 active, #100727 B 0.0363 active, #100728 B 0.0363 active, #100729 B 0.0363 active, #100730 B 0.0363 active, #100731 B 0.0363 active, #100732 B 0.0363 active, #100733 B 0.0363 active, #100734 B 0.0363 active, #100735 B 0.0363 active, #100736 B 0.0363 settled/bid_eth, #100737 B 0.0363 active, #100738 B 0.0363 active, #100739 B 0.0363 active, #100740 B 0.0363 active, #100741 B 0.0363 active, #100742 B 0.0363 active, #100743 B 0.0363 active, #100744 B 0.0363 active, #100745 B 0.0363 active, #100746 B 0.0363 active, #100747 B 0.0363 active, #100748 B 0.0363 active, #100749 B 0.0363 active, #100750 B 0.0363 active, #100751 B 0.0363 active, #100752 B 0.0363 active, #100753 B 0.0363 active, #100754 B 0.0363 active, #100755 B 0.0363 active, #100756 B 0.0363 active, #100757 B 0.0363 active, #100758 B 0.0363 active, #100759 B 0.0363 active, #100792 B 0.0360 active, #100795 B 0.0360 active, #100796 B 0.0360 active, #100797 B 0.0360 active, #100798 B 0.0360 active, #100832 B 0.0300 active, #100845 B 0.0363 active, #100846 B 0.0363 active, #100847 B 0.0363 active, #100848 B 0.0363 active, #100849 B 0.0363 active, #100850 B 0.0363 active, #100851 B 0.0363 active, #100852 B 0.0363 active, #100853 B 0.0363 active, #100854 B 0.0363 active, #100855 B 0.0360 active, #100856 B 0.0363 active, #100857 B 0.0360 active, #100858 B 0.0360 active, #100859 B 0.0363 active, #100860 B 0.0360 active, #100861 B 0.0363 active, #100862 B 0.0360 active, #100863 B 0.0360 active, #100864 B 0.0363 active, #100865 B 0.0360 active, #100866 B 0.0360 active, #100867 B 0.0360 active, #100868 B 0.0360 active, #100869 B 0.0360 active, #100872 B 0.0361 active, #100873 B 0.0360 active, #100874 B 0.0360 active, #100875 B 0.0360 active, #100876 B 0.0360 active, #100877 B 0.0360 active, #100878 B 0.0361 active, #100879 B 0.0361 active, #100880 B 0.0361 active, #100881 B 0.0361 active, #100882 B 0.0361 active, #100883 B 0.0361 active, #100884 B 0.0361 active, #100885 B 0.0360 active, #100886 B 0.0360 active, #100887 B 0.0360 active, #100888 B 0.0360 active, #100889 B 0.0360 active, #100890 B 0.0360 active, #100891 B 0.0360 active, #100892 B 0.0361 active
