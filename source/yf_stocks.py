"""
Text Expander - B3 stock fundamentals lookup module
Uses the yfinance library (https://github.com/ranaroussi/yfinance)
A mature library widely used by the community

Installation: pip install yfinance
"""

from datetime import datetime

# yfinance drags in pandas/numpy (seconds of import time, tens of MB in the build).
# It is imported lazily inside the fetch path so app startup stays fast; these
# snippets are occasional and already run on a background thread (audit 2.4).

class B3FundamentosConsultor:
    """Class for querying B3 and US stock fundamentals via yfinance."""
    
    
    def __init__(self, cache_seconds=600):
        """
        Initialize the consultor
        
        Args:
            cache_seconds: Data cache duration (seconds) - default 10 minutes
        """
        self.cache_seconds = cache_seconds
        self._cache = {}
    
    def _format_ticker(self, ticker):
        """
        Format the ticker to the correct standard
        - Brazilian stocks: append .SA when it contains digits (e.g. PETR4 -> PETR4.SA)
        - US stocks: use as-is (e.g. AAPL, MSFT, GOOGL)
        """
        ticker = ticker.upper().strip()
        
        # Already suffixed with .SA: use as-is
        if ticker.endswith('.SA'):
            return ticker
        
        # If it contains digits, it's a Brazilian stock (append .SA)
        if any(char.isdigit() for char in ticker):
            return ticker + '.SA'
        
        # Otherwise it's a US stock (use as-is)
        return ticker
    
    def _get_cached_or_fetch(self, key, fetch_func):
        """Return cached data, or fetch fresh data if expired."""
        now = datetime.now()
        
        if key in self._cache:
            data, timestamp = self._cache[key]
            if (now - timestamp).total_seconds() < self.cache_seconds:
                return data
        
        try:
            data = fetch_func()
            self._cache[key] = (data, now)
            return data
        except Exception as e:
            # On failure, fall back to the stale cache
            if key in self._cache:
                return self._cache[key][0]
            return f"[Erro: {str(e)}]"
    
    def _get_ticker_object(self, ticker):
        """Return a cached yfinance Ticker object."""
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_obj"
        
        def fetch():
            import yfinance as yf
            return yf.Ticker(ticker_fmt)
        
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def _format_currency(self, value, ticker_info=None):
        """Format a value as abbreviated currency (R$ for BR, $ for US) with the correct locale."""
        if value is None or value == 'N/A':
            return "N/A"
        try:
            # Detect currency
            currency = "R$"
            if ticker_info and self._safe_get(ticker_info, 'currency') == 'USD':
                currency = "$"

            num = float(value)
            suffix = ""

            # Set the scale (B / M / plain)
            if abs(num) >= 1_000_000_000:
                num = num / 1_000_000_000
                suffix = " B"
            elif abs(num) >= 1_000_000:
                num = num / 1_000_000
                suffix = " M"

            if currency == "R$":
                # Brazilian format: decimal comma, thousands dot
                formatted = f"{num:,.1f}"  # 1 decimal place, e.g. 421,5
                formatted = formatted.replace(',', '_').replace('.', ',').replace('_', '.')
                return f"{currency} {formatted}{suffix}"
            else:
                # US format: decimal point, thousands comma
                formatted = f"{num:,.1f}"
                return f"{currency} {formatted}{suffix}"

        except Exception:
            return "N/A"

    
    def _format_number(self, value, decimals=2, currency="BRL"):
        """Format a generic number with the proper separator (comma for BR, point for US)."""
        if value is None or value == 'N/A':
            return "N/A"
        try:
            formatted = f"{value:.{decimals}f}"

            if currency == "USD":
                return formatted  # keeps 278.78

            # default -> BRL
            return formatted.replace('.', ',')
        except Exception:
            return "N/A"

    
    def _safe_get(self, data, key, default=None):
        """Safely get a value from the dictionary."""
        try:
            value = data.get(key, default)
            if value is None or (isinstance(value, float) and value != value):  # NaN check
                return default
            return value
        except Exception:
            return default
    
    def get_cotacao_atual(self, ticker):
        """Return the stock's current quote."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                preco = self._safe_get(info, 'currentPrice') or self._safe_get(info, 'regularMarketPrice')
                currency = self._safe_get(info, 'currency', 'BRL')
                symbol = "R$" if currency == 'BRL' else "$"
                
                if preco:
                    return f"Cotação {ticker}: {symbol} {self._format_number(preco, 2, currency)}"
                return "Cotação: N/A"
            except Exception as e:
                return f"Cotação: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_preco"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_market_cap(self, ticker):
        """Return Market Cap (market value)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                mcap = self._safe_get(info, 'marketCap')
                
                if mcap:
                    return f"Market Cap {ticker}: {self._format_currency(mcap, info)}"
                return "Market Cap: N/A"
            except Exception:
                return "Market Cap: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_mcap"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_preco_lucro(self, ticker):
        """Return P/L (price-to-earnings)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                pl = self._safe_get(info, 'trailingPE') or self._safe_get(info, 'forwardPE')
                
                if pl:
                    return f"P/L {ticker}: {self._format_number(pl, 2)}"
                return "P/L: N/A"
            except Exception:
                return "P/L: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_pl"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_preco_vp(self, ticker):
        """Return P/VP (price-to-book)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                pvp = self._safe_get(info, 'priceToBook')
                
                if pvp:
                    return f"P/VP {ticker}: {self._format_number(pvp, 2)}"
                return "P/VP: N/A"
            except Exception:
                return "P/VP: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_pvp"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_dividend_yield(self, ticker):
        """Return Dividend Yield (%)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                dy = self._safe_get(info, 'dividendYield')
                
                if dy and dy > 0:
                    return f"DY {ticker}: {self._format_number(dy, 2)}%"
                return "DY: N/A"
            except Exception:
                return "DY: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_dy"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_ebitda(self, ticker):
        """Return EBITDA."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                ebitda = self._safe_get(info, 'ebitda')
                
                if ebitda:
                    return f"EBITDA {ticker}: {self._format_currency(ebitda, info)}"
                return "EBITDA: N/A"
            except Exception:
                return "EBITDA: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_ebitda"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_margem_liquida(self, ticker):
        """Return net margin."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                margem = self._safe_get(info, 'profitMargins')
                
                if margem:
                    return f"Margem Líq. {ticker}: {self._format_number(margem * 100, 2)}%"
                return "Margem Líq.: N/A"
            except Exception:
                return "Margem Líq.: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_margem"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_roe(self, ticker):
        """Return ROE (Return on Equity)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                roe = self._safe_get(info, 'returnOnEquity')
                
                if roe:
                    return f"ROE {ticker}: {self._format_number(roe * 100, 2)}%"
                return "ROE: N/A"
            except Exception:
                return "ROE: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_roe"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_divida_total(self, ticker):
        """Return total debt."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                divida_total = self._safe_get(info, 'totalDebt')

                if divida_total is not None:
                    return f"Dív. Total {ticker}: {self._format_currency(divida_total, info)}"
                return "Dív. Total: N/A"
            except Exception:
                return "Dív. Total: N/A"

        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_div_total"
        return self._get_cached_or_fetch(cache_key, fetch)

    def get_caixa(self, ticker):
        """Return cash (Total Cash)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                caixa = self._safe_get(info, 'totalCash')

                if caixa is not None:
                    return f"Caixa {ticker}: {self._format_currency(caixa, info)}"
                return "Caixa: N/A"
            except Exception:
                return "Caixa: N/A"

        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_caixa"
        return self._get_cached_or_fetch(cache_key, fetch)

    def get_divida_liquida(self, ticker):
        """Return net debt (total debt - cash)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                divida_total = self._safe_get(info, 'totalDebt')
                caixa = self._safe_get(info, 'totalCash')

                if divida_total is not None and caixa is not None:
                    div_liquida = divida_total - caixa
                    return f"Dív. Líq. {ticker}: {self._format_currency(div_liquida, info)}"
                # If we only have the debt, we can still return something useful
                if divida_total is not None:
                    return f"Dív. Líq. {ticker}: {self._format_currency(divida_total, info)} (sem caixa)"
                return "Dív. Líq.: N/A"
            except Exception:
                return "Dív. Líq.: N/A"

        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_div_liq"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_receita_liquida(self, ticker):
        """Return net revenue."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                receita = self._safe_get(info, 'totalRevenue')
                
                if receita:
                    return f"Receita Líq. {ticker}: {self._format_currency(receita, info)}"
                return "Receita Líq.: N/A"
            except Exception:
                return "Receita Líq.: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_receita"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_beta(self, ticker):
        """Return Beta (volatility relative to the market)."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                beta = self._safe_get(info, 'beta')
                
                if beta:
                    # Beta interpretation
                    if beta < 1:
                        interpretacao = "(menos volátil que o mercado)"
                    elif beta == 1:
                        interpretacao = "(igual ao mercado)"
                    else:
                        interpretacao = "(mais volátil que o mercado)"
                    
                    return f"Beta {ticker}: {self._format_number(beta, 2)} {interpretacao}"
                return "Beta: N/A"
            except Exception:
                return "Beta: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_beta"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_52week_high_low(self, ticker):
        """Return the 52-week high and low."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                high_52 = self._safe_get(info, 'fiftyTwoWeekHigh')
                low_52 = self._safe_get(info, 'fiftyTwoWeekLow')
                preco_atual = self._safe_get(info, 'currentPrice') or self._safe_get(info, 'regularMarketPrice')
                currency = self._safe_get(info, 'currency', 'BRL')
                symbol = "R$" if currency == 'BRL' else "$"
                
                if high_52 and low_52:
                    resultado = f"52 Semanas {ticker}: "
                    resultado += f"Mín {symbol} {self._format_number(low_52, 2, currency)} | "
                    resultado += f"Máx {symbol} {self._format_number(high_52, 2, currency)}"
                    
                    # Compute distance from the high/low when the current price is available
                    if preco_atual:
                        variacao_max = ((preco_atual - high_52) / high_52) * 100
                        variacao_min = ((preco_atual - low_52) / low_52) * 100
                        
                        if abs(variacao_max) < 5:
                            resultado += " (próximo da máxima)"
                        elif abs(variacao_min) < 5:
                            resultado += " (próximo da mínima)"
                    
                    return resultado
                return "52 Semanas: N/A"
            except Exception:
                return "52 Semanas: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_52w"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_volume_medio(self, ticker):
        """Return the average daily volume."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                volume = self._safe_get(info, 'averageDailyVolume10Day') or self._safe_get(info, 'averageVolume')
                
                if volume:
                    if volume >= 1_000_000:
                        return f"Vol. Médio {ticker}: {volume/1_000_000:.1f} M"
                    else:
                        return f"Vol. Médio {ticker}: {volume:,.0f}".replace(',', '.')
                return "Vol. Médio: N/A"
            except Exception:
                return "Vol. Médio: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_volume"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_resumo_fundamentos(self, ticker):
        """Full fundamentals summary with emojis."""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info

                ticker_fmt = self._safe_get(info, 'symbol', self._format_ticker(ticker))
                currency = self._safe_get(info, 'currency', 'BRL')
                symbol = "R$" if currency == 'BRL' else "$"

                # Quote
                preco = (self._safe_get(info, 'currentPrice')
                            or self._safe_get(info, 'regularMarketPrice'))
                preco_str = f"{symbol} {self._format_number(preco, 2, currency)}" if preco else "N/A"

                # 52 Weeks High/Low
                high_52 = self._safe_get(info, 'fiftyTwoWeekHigh')
                low_52 = self._safe_get(info, 'fiftyTwoWeekLow')
                if high_52 and low_52:
                    high_52_str = f"{symbol} {self._format_number(high_52, 2, currency)}"
                    low_52_str = f"{symbol} {self._format_number(low_52, 2, currency)}"
                    semanas_52_str = f"Mín {low_52_str} | Máx {high_52_str}"
                else:
                    semanas_52_str = "N/A"

                # Beta
                beta = self._safe_get(info, 'beta')
                beta_str = self._format_number(beta, 2, currency) if beta else "N/A"

                # Market Cap
                mcap = self._safe_get(info, 'marketCap')
                mcap_str = self._format_currency(mcap, info) if mcap else "N/A"

                # Net revenue
                receita = self._safe_get(info, 'totalRevenue')
                receita_str = self._format_currency(receita, info) if receita else "N/A"

                # EBITDA
                ebitda = self._safe_get(info, 'ebitda')
                ebitda_str = self._format_currency(ebitda, info) if ebitda else "N/A"

                # Net income
                lucro = (self._safe_get(info, 'netIncomeToCommon')
                            or self._safe_get(info, 'netIncome'))
                lucro_str = self._format_currency(lucro, info) if lucro else "N/A"

                # Net margin
                margem = self._safe_get(info, 'profitMargins')
                margem_str = f"{self._format_number(margem * 100, 2, currency)}%" if margem else "N/A"

                # P/L
                pl = (self._safe_get(info, 'trailingPE')
                        or self._safe_get(info, 'forwardPE'))
                pl_str = self._format_number(pl, 2, currency) if pl else "N/A"

                # Dividend Yield
                dy = self._safe_get(info, 'dividendYield')
                dy_str = f"{self._format_number(dy, 2, currency)}%" if dy and dy > 0 else "N/A"

                # P/VP
                pvp = self._safe_get(info, 'priceToBook')
                pvp_str = self._format_number(pvp, 2, currency) if pvp else "N/A"
                
                # ROE
                roe = self._safe_get(info, 'returnOnEquity')
                roe_str = f"{self._format_number(roe * 100, 2, currency)}%" if roe else "N/A"

                # Total debt, net debt and cash
                div_total = self._safe_get(info, 'totalDebt')
                div_total_str = self._format_currency(div_total, info) if div_total else "N/A"
                
                caixa = self._safe_get(info, 'totalCash')
                caixa_str = self._format_currency(caixa, info) if caixa else "N/A"
                
                if div_total and caixa:
                    div_liq = div_total - caixa
                    div_liq_str = self._format_currency(div_liq, info)
                else:
                    div_liq_str = "N/A"

                linhas = [
                    f"📈 {ticker}  |  {preco_str}",
                    f"📊 52 Semanas: {semanas_52_str}",
                    f"🎲 Beta: {beta_str}",
                    f"🏢 Market Cap: {mcap_str}",
                    f"💰 Receita Líq.: {receita_str}",
                    f"🏭 EBITDA: {ebitda_str}",
                    f"🧾 Lucro Líquido: {lucro_str}",
                    f"📊 Margem Líq.: {margem_str}",
                    f"💸 Dívida Total: {div_total_str}",
                    f"💵 Caixa: {caixa_str}",
                    f"⚖️ Dívida Líq.: {div_liq_str}",
                    f"📐 P/L: {pl_str}",
                    f"💵 DY: {dy_str}",
                    f"📘 P/VP: {pvp_str}",
                    f"🎯 ROE: {roe_str}",
                ]

                return "\n".join(linhas)

            except Exception as e:
                return f"[Erro ao gerar resumo: {str(e)}]"

        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_resumo"
        return self._get_cached_or_fetch(cache_key, fetch)


# Standalone usage example (for testing)
if __name__ == "__main__":
    print("=" * 60)
    print("TESTANDO NOVOS INDICADORES")
    print("=" * 60)
    
    b3 = B3FundamentosConsultor()
    
    ticker = "PETR4"
    print(f"\n🔍 Testando novos indicadores para {ticker}")
    print("=" * 60)
    
    print("\n" + b3.get_receita_liquida(ticker))
    print(b3.get_beta(ticker))
    print(b3.get_52week_high_low(ticker))
    
    print("\n" + "=" * 60)
    print("RESUMO COMPLETO ATUALIZADO - PETR4")
    print("=" * 60)
    print(b3.get_resumo_fundamentos(ticker))
    
    print("\n\n" + "=" * 60)
    print("TESTANDO COM AÇÃO AMERICANA - AAPL")
    print("=" * 60)
    
    print("\n" + b3.get_receita_liquida("AAPL"))
    print(b3.get_beta("AAPL"))
    print(b3.get_52week_high_low("AAPL"))
    
    print("\n" + "=" * 60)
    print("RESUMO COMPLETO - AAPL")
    print("=" * 60)
    print(b3.get_resumo_fundamentos("AAPL"))
    
    print("\n✓ Testes concluídos!")