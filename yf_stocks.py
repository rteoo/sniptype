"""
Text Expander - Módulo de consulta de dados fundamentalistas de ações B3
Usa a biblioteca yfinance (https://github.com/ranaroussi/yfinance)
Biblioteca consolidada e amplamente usada pela comunidade

Instalação: pip install yfinance
"""

import yfinance as yf
from datetime import datetime

class B3FundamentosConsultor:
    """Classe para consultar dados fundamentalistas de ações B3 e US via yfinance"""
    
    
    def __init__(self, cache_seconds=600):
        """
        Inicializa o consultor
        
        Args:
            cache_seconds: Tempo de cache dos dados (segundos) - padrão 10 minutos
        """
        self.cache_seconds = cache_seconds
        self._cache = {}
    
    def _format_ticker(self, ticker):
        """
        Formata o ticker para o padrão correto
        - Ações brasileiras: adiciona .SA se tiver números (ex: PETR4 -> PETR4.SA)
        - Ações americanas: usa direto (ex: AAPL, MSFT, GOOGL)
        """
        ticker = ticker.upper().strip()
        
        # Remove .SA se já existir
        if ticker.endswith('.SA'):
            return ticker
        
        # Se contém números, é ação brasileira (adiciona .SA)
        if any(char.isdigit() for char in ticker):
            return ticker + '.SA'
        
        # Senão, é ação americana (usa direto)
        return ticker
    
    def _get_cached_or_fetch(self, key, fetch_func):
        """Retorna dados do cache ou busca novos se expirado"""
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
            # Se falhar, tenta usar cache antigo
            if key in self._cache:
                return self._cache[key][0]
            return f"[Erro: {str(e)}]"
    
    def _get_ticker_object(self, ticker):
        """Retorna objeto Ticker do yfinance com cache"""
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_obj"
        
        def fetch():
            return yf.Ticker(ticker_fmt)
        
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def _format_currency(self, value, ticker_info=None):
        """Formata valor em moeda abreviada (R$ para BR, $ para US) com locale correto."""
        if value is None or value == 'N/A':
            return "N/A"
        try:
            # Detecta moeda
            currency = "R$"
            if ticker_info and self._safe_get(ticker_info, 'currency') == 'USD':
                currency = "$"

            num = float(value)
            suffix = ""

            # Define escala (B / M / normal)
            if abs(num) >= 1_000_000_000:
                num = num / 1_000_000_000
                suffix = " B"
            elif abs(num) >= 1_000_000:
                num = num / 1_000_000
                suffix = " M"

            if currency == "R$":
                # Formato brasileiro: vírgula decimal, ponto de milhar
                formatted = f"{num:,.1f}"  # 1 casa decimal, ex: 421,5
                formatted = formatted.replace(',', '_').replace('.', ',').replace('_', '.')
                return f"{currency} {formatted}{suffix}"
            else:
                # Formato US: ponto decimal, vírgula de milhar
                formatted = f"{num:,.1f}"
                return f"{currency} {formatted}{suffix}"

        except Exception:
            return "N/A"

    
    def _format_number(self, value, decimals=2, currency="BRL"):
        """Formata número genérico com separador adequado (vírgula BR, ponto EUA)."""
        if value is None or value == 'N/A':
            return "N/A"
        try:
            formatted = f"{value:.{decimals}f}"

            if currency == "USD":
                return formatted  # mantém 278.78

            # default -> BRL
            return formatted.replace('.', ',')
        except:
            return "N/A"

    
    def _safe_get(self, data, key, default=None):
        """Obtém valor de forma segura do dicionário"""
        try:
            value = data.get(key, default)
            if value is None or (isinstance(value, float) and value != value):  # NaN check
                return default
            return value
        except:
            return default
    
    def get_cotacao_atual(self, ticker):
        """Retorna cotação atual da ação"""
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
        """Retorna Market Cap (Valor de Mercado)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                mcap = self._safe_get(info, 'marketCap')
                
                if mcap:
                    return f"Market Cap {ticker}: {self._format_currency(mcap, info)}"
                return "Market Cap: N/A"
            except:
                return "Market Cap: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_mcap"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_preco_lucro(self, ticker):
        """Retorna P/L (Preço/Lucro)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                pl = self._safe_get(info, 'trailingPE') or self._safe_get(info, 'forwardPE')
                
                if pl:
                    return f"P/L {ticker}: {self._format_number(pl, 2)}"
                return "P/L: N/A"
            except:
                return "P/L: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_pl"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_preco_vp(self, ticker):
        """Retorna P/VP (Preço sobre Valor Patrimonial)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                pvp = self._safe_get(info, 'priceToBook')
                
                if pvp:
                    return f"P/VP {ticker}: {self._format_number(pvp, 2)}"
                return "P/VP: N/A"
            except:
                return "P/VP: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_pvp"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_dividend_yield(self, ticker):
        """Retorna Dividend Yield (%)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                dy = self._safe_get(info, 'dividendYield')
                
                if dy and dy > 0:
                    return f"DY {ticker}: {self._format_number(dy, 2)}%"
                return "DY: N/A"
            except:
                return "DY: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_dy"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_ebitda(self, ticker):
        """Retorna EBITDA"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                ebitda = self._safe_get(info, 'ebitda')
                
                if ebitda:
                    return f"EBITDA {ticker}: {self._format_currency(ebitda, info)}"
                return "EBITDA: N/A"
            except:
                return "EBITDA: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_ebitda"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_margem_liquida(self, ticker):
        """Retorna Margem Líquida"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                margem = self._safe_get(info, 'profitMargins')
                
                if margem:
                    return f"Margem Líq. {ticker}: {self._format_number(margem * 100, 2)}%"
                return "Margem Líq.: N/A"
            except:
                return "Margem Líq.: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_margem"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_roe(self, ticker):
        """Retorna ROE (Return on Equity)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                roe = self._safe_get(info, 'returnOnEquity')
                
                if roe:
                    return f"ROE {ticker}: {self._format_number(roe * 100, 2)}%"
                return "ROE: N/A"
            except:
                return "ROE: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_roe"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_divida_total(self, ticker):
        """Retorna Dívida Total"""
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
        """Retorna Caixa (Total Cash)"""
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
        """Retorna Dívida Líquida (Dívida Total - Caixa)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                divida_total = self._safe_get(info, 'totalDebt')
                caixa = self._safe_get(info, 'totalCash')

                if divida_total is not None and caixa is not None:
                    div_liquida = divida_total - caixa
                    return f"Dív. Líq. {ticker}: {self._format_currency(div_liquida, info)}"
                # Se só tiver dívida, ainda podemos retornar algo útil
                if divida_total is not None:
                    return f"Dív. Líq. {ticker}: {self._format_currency(divida_total, info)} (sem caixa)"
                return "Dív. Líq.: N/A"
            except Exception:
                return "Dív. Líq.: N/A"

        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_div_liq"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_receita_liquida(self, ticker):
        """Retorna Receita Líquida (Revenue)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                receita = self._safe_get(info, 'totalRevenue')
                
                if receita:
                    return f"Receita Líq. {ticker}: {self._format_currency(receita, info)}"
                return "Receita Líq.: N/A"
            except:
                return "Receita Líq.: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_receita"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_beta(self, ticker):
        """Retorna Beta (Volatilidade em relação ao mercado)"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info
                beta = self._safe_get(info, 'beta')
                
                if beta:
                    # Interpretação do Beta
                    if beta < 1:
                        interpretacao = "(menos volátil que o mercado)"
                    elif beta == 1:
                        interpretacao = "(igual ao mercado)"
                    else:
                        interpretacao = "(mais volátil que o mercado)"
                    
                    return f"Beta {ticker}: {self._format_number(beta, 2)} {interpretacao}"
                return "Beta: N/A"
            except:
                return "Beta: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_beta"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_52week_high_low(self, ticker):
        """Retorna Máxima e Mínima de 52 semanas"""
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
                    
                    # Calcula distância da máxima/mínima se tiver preço atual
                    if preco_atual:
                        variacao_max = ((preco_atual - high_52) / high_52) * 100
                        variacao_min = ((preco_atual - low_52) / low_52) * 100
                        
                        if abs(variacao_max) < 5:
                            resultado += " (próximo da máxima)"
                        elif abs(variacao_min) < 5:
                            resultado += " (próximo da mínima)"
                    
                    return resultado
                return "52 Semanas: N/A"
            except:
                return "52 Semanas: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_52w"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_volume_medio(self, ticker):
        """Retorna Volume Médio Diário"""
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
            except:
                return "Vol. Médio: N/A"
        
        ticker_fmt = self._format_ticker(ticker)
        cache_key = f"{ticker_fmt}_volume"
        return self._get_cached_or_fetch(cache_key, fetch)
    
    def get_resumo_fundamentos(self, ticker):
        """Resumo completo dos fundamentos com emojis"""
        def fetch():
            try:
                ticker_obj = self._get_ticker_object(ticker)
                info = ticker_obj.info

                ticker_fmt = self._safe_get(info, 'symbol', self._format_ticker(ticker))
                currency = self._safe_get(info, 'currency', 'BRL')
                symbol = "R$" if currency == 'BRL' else "$"

                # Cotação
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

                # Receita Líquida
                receita = self._safe_get(info, 'totalRevenue')
                receita_str = self._format_currency(receita, info) if receita else "N/A"

                # EBITDA
                ebitda = self._safe_get(info, 'ebitda')
                ebitda_str = self._format_currency(ebitda, info) if ebitda else "N/A"

                # Lucro Líquido
                lucro = (self._safe_get(info, 'netIncomeToCommon')
                            or self._safe_get(info, 'netIncome'))
                lucro_str = self._format_currency(lucro, info) if lucro else "N/A"

                # Margem Líquida
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

                # Dívida total, líquida e caixa
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


# Exemplo de uso standalone (para testes)
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