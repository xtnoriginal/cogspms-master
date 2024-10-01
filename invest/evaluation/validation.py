import math

import numpy as np
import pandas as pd

import invest.metrics.return_ as return_metrics
from invest.preprocessing.dataloader import load_benchmark_data


def process_metrics(df, prices_initial_dict, prices_current_dict, share_betas_dict, start_year,
                    end_year, index_code):
    """
    Processes risk return metrics (Annual Return, Compound Return, Annual Average Return) for selected portfolio
    """
    annual_returns = []
    total_return = 0
    for year in range(start_year, end_year):
        return_ = sum(prices_current_dict[str(year)]) - sum(prices_initial_dict[str(year)])
        total_return += return_
        if np.abs(return_) > 0:
            annual_return = return_metrics.annual_return(np.array(prices_initial_dict[str(year)]),
                                                         np.array(prices_current_dict[str(year)]))
        else:
            annual_return = 0
        annual_returns.append(annual_return)
    print("\nAnnual Returns")
    print("IP." + index_code, ["{}%".format(round(v * 100, 2)) for v in annual_returns])

    pv = sum(prices_initial_dict[str(start_year)])
    y = start_year
    while pv == 0 and y != (end_year - 1):
        y += 1
        pv = sum(prices_initial_dict[str(y)])
    pv_ = pv + total_return
    n = end_year - start_year
    if np.abs(pv_ - pv) > 0:
        compound_return = return_metrics.compound_return(pv, pv_, n)
    else:
        compound_return = 0
    average_annual_return = return_metrics.average_annual_return(annual_returns)
    print("Performance Metrics")
    print('IP.{} | CR {:5.2f}% | AAR {:5.2f}%'.format(index_code, compound_return * 100,
                                                      average_annual_return * 100))
    treynor_ratio, sharpe_ratio = process_risk_adjusted_return_metrics(df, share_betas_dict, start_year, end_year,
                                                                       compound_return,
                                                                       average_annual_return, annual_returns,
                                                                       index_code)

    return annual_returns, compound_return, average_annual_return, treynor_ratio, sharpe_ratio


def process_risk_adjusted_return_metrics(df, share_betas_dict,
                                         start_year, end_year, compound_return, average_annual_return,
                                         annual_returns, index_code):
    """
    Processes risk adjusted return metrics (Treynor Ratio, Sharpe Ratio) for selected portfolio
    """
    portfolio_return = compound_return * 100
    betas = []
    rf = []
    for year in range(start_year, end_year):
        betas += share_betas_dict[str(year)]
        mask = (df['Date'] >= str(year) + '-01-01') & (df['Date'] <= str(year) + '-12-31')
        rf.append(df[mask].iloc[-1]['RiskFreeRateOfReturn'] / 100)
    beta_portfolio = np.mean(betas)
    risk_free_rate = np.mean(rf)

    if beta_portfolio > 0:
        treynor_ratio = return_metrics.treynor_ratio(portfolio_return, risk_free_rate, beta_portfolio)
    else:
        treynor_ratio = 0

    delta = average_annual_return - np.mean(rf)
    excess_returns = []
    for i, annual_return in enumerate(annual_returns):
        excess_returns.append(annual_return - rf[i])

    v = 0
    for e in excess_returns:
        v += (e - delta) ** 2
    standard_deviation_excess_return = math.sqrt(v)
    sharpe_ratio = return_metrics.sharpe_ratio(portfolio_return, risk_free_rate, standard_deviation_excess_return)
    print('IP.{} | Treynor Ratio {:5.2f} | Sharpe Ratio: {:5.2f}'.format(index_code, treynor_ratio, sharpe_ratio))

    return treynor_ratio, sharpe_ratio


def process_benchmark_metrics(start_year, end_year, index_code, holding_period=-1):
    """
    Processes risk return metrics (Annual Return, Compound Return, Annual Average Return) for selected benchmark
    """
    df = load_benchmark_data(index_code)
    annual_returns = []
    total_return = 0
    for year in range(start_year, end_year):
        mask = (df['Date'] >= str(year) + '/01/01') & (df['Date'] <= str(year) + '/12/31')
        pv = float(df.loc[mask, 'Close'].iloc[0].replace(',', '.'))
        pv_ = float(df.loc[mask, 'Close'].iloc[holding_period].replace(',', '.'))
        return_ = pv_ - pv
        total_return += return_
        if np.abs(return_) > 0:
            annual_return = return_metrics.annual_return(pv, pv_)
        else:
            annual_return = 0
        annual_returns.append(annual_return)
    print("\nAnnual Returns")
    print("Benchmark." + index_code, ["{}%".format(round(v * 100, 2)) for v in annual_returns])

    mask = (df['Date'] >= str(start_year) + '/01/01') & (df['Date'] <= str(start_year) + '/12/31')
    pv = float(df.loc[mask, 'Close'].iloc[0].replace(',', '.'))
    y = start_year
    while pv == 0 and y != end_year:
        y += 1
        mask = (df['Date'] >= str(y) + '-01-01') & (df['Date'] <= str(y) + '-12-31')
        pv = float(df.loc[mask, 'Close'].iloc[0].replace(',', '.'))
    pv_ = pv + total_return
    n = end_year - start_year
    compound_return = return_metrics.compound_return(pv, pv_, n)
    average_annual_return = return_metrics.average_annual_return(annual_returns)

    print("Performance Measures")
    print('Benchmark.{} | CR {:5.2f}% | AAR {:5.2f}%'.format(index_code, compound_return * 100,
                                                             average_annual_return * 100))
    treynor_ratio, sharpe_ratio = process_benchmark_risk_adjusted_return_metrics(df, start_year, end_year, index_code,
                                                                                 compound_return,
                                                                                 average_annual_return, annual_returns)

    return annual_returns, compound_return, average_annual_return, treynor_ratio, sharpe_ratio


def process_benchmark_risk_adjusted_return_metrics(df, start_year, end_year, index_code, compound_return,
                                                   average_annual_return, annual_returns):
    """
    Processes risk adjusted return metrics (Treynor Ratio, Sharpe Ratio) for selected benchmark
    """
    df_ = pd.read_csv('data/INVEST_clean.csv')
    portfolio_return = compound_return * 100
    rf = []
    for year in range(start_year, end_year):
        mask = (df_['Date'] >= str(year) + '-01-01') & (df_['Date'] <= str(year) + '-12-31')
        rf.append(df_[mask].iloc[-1]['RiskFreeRateOfReturn'] / 100)

    mask = (df['Date'] >= str(start_year) + '/01/01') & (df['Date'] <= str(start_year) + '/12/31')
    df.loc[mask, 'Beta Weekly Leveraged'] = [x.replace(',', '.') for x in df.loc[mask, 'Beta Weekly Leveraged']]
    beta_portfolio = np.mean(df.loc[mask, 'Beta Weekly Leveraged'].values.astype(np.float32))
    risk_free_rate = np.mean(rf)

    treynor_ratio = return_metrics.treynor_ratio(portfolio_return, risk_free_rate, beta_portfolio)

    delta = average_annual_return - np.mean(rf)
    excess_returns = []
    for i, annual_return in enumerate(annual_returns):
        excess_returns.append(annual_return - rf[i])

    v = 0
    for e in excess_returns:
        v += (e - delta) ** 2
    standard_deviation_excess_return = math.sqrt(v)
    sharpe_ratio = return_metrics.sharpe_ratio(portfolio_return, risk_free_rate, standard_deviation_excess_return)
    print(
        'Benchmark.{} | Treynor Ratio {:5.2f} | Sharpe Ratio: {:5.2f}'.format(index_code, treynor_ratio, sharpe_ratio))

    return treynor_ratio, sharpe_ratio
