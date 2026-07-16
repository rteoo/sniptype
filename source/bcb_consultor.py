"""
Txt Xpander - Brazilian Central Bank API lookup module
"""

import json
from urllib.request import urlopen
from urllib.error import URLError
from datetime import datetime, timedelta

class BCBConsultor:
    """Class for querying the Brazilian Central Bank API."""
    
    BASE_URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados/ultimos/1?formato=json"
    BASE_URL_PTAX = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarDia(dataCotacao=@dataCotacao)?@dataCotacao='{}'&$format=json"
    
    # SGS series codes (Sistema Gerenciador de Séries Temporais)
    SERIES = {
        'selic_meta': 432,     # Selic target set by COPOM
        'ipcam': 433,          # IPCA (% monthly)
        'ipca12': 13522,       # IPCA accumulated 12-month variation (%)
        'cdi': 12,             # CDI rate (% accumulated in the month)
        'ptax': 1,             # PTAX buy rate (R$)
    }
    
    def __init__(self, timeout=5, cache_seconds=300):
        """
        Initialize the consultor
        
        Args:
            timeout: Maximum time to wait for the response (seconds)
            cache_seconds: Data cache duration (seconds)
        """
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache = {}
    
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
    
    def _fetch_sgs(self, codigo_serie):
        """Fetch data for an SGS series."""
        url = self.BASE_URL_SGS.format(codigo_serie)
        with urlopen(url, timeout=self.timeout) as response:
            data = json.loads(response.read().decode())
            if data and len(data) > 0:
                return {
                    'valor': float(data[0]['valor']),
                    'data': data[0]['data']
                }
        return None
    
    def _fetch_dolar(self):
        """Fetch the PTAX dollar quote."""
        # Try today; if unavailable, try previous days
        for days_ago in range(5):
            data = (datetime.now() - timedelta(days=days_ago)).strftime('%m-%d-%Y')
            url = self.BASE_URL_PTAX.format(data)
            
            try:
                with urlopen(url, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode())
                    if 'value' in result and len(result['value']) > 0:
                        cotacao = result['value'][0]
                        return {
                            'compra': float(cotacao['cotacaoCompra']),
                            'venda': float(cotacao['cotacaoVenda']),
                            'data': cotacao['dataHoraCotacao'][:10]
                        }
            except Exception:
                continue
        
        return None
    
    def get_dolar(self):
        """Return the formatted dollar quote."""
        def fetch():
            data = self._fetch_dolar()
            if data:
                return f"US$ 1,00 = R$ {data['venda']:.2f} (compra: R$ {data['compra']:.2f}) - {data['data']}"
            return "[Cotação indisponível]"
        
        return self._get_cached_or_fetch('dolar', fetch)
    
    def get_selic_meta(self):
        """Return the formatted Selic target."""
        def fetch():
            data = self._fetch_sgs(self.SERIES['selic_meta'])
            if data:
                return f"Taxa Selic: {data['valor']:.2f}% a.a. (ref: {data['data']})"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('selic_meta', fetch)
    
    def get_ipca_mensal(self):
        """Return the formatted monthly IPCA."""
        def fetch():
            data = self._fetch_sgs(self.SERIES['ipcam'])
            if data:
                # Convert date from dd/mm/yyyy to mm/yyyy
                data_partes = data['data'].split('/')
                mes_ano = f"{data_partes[1]}/{data_partes[2]}"
                return f"IPCA Mensal: {data['valor']:.2f}% ref. {mes_ano}"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('ipcam', fetch)
    
    def get_ipca_12m(self):
        """Return the formatted 12-month IPCA."""
        def fetch():
            data = self._fetch_sgs(self.SERIES['ipca12'])
            if data:
                # Convert date from dd/mm/yyyy to mm/yyyy
                data_partes = data['data'].split('/')
                mes_ano = f"{data_partes[1]}/{data_partes[2]}"
                return f"IPCA 12 Meses: {data['valor']:.2f}% ref. {mes_ano}"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('ipca12', fetch)
    
    def get_cdi(self):
        """Return the formatted month-to-date CDI rate."""
        def fetch():
            data = self._fetch_sgs(self.SERIES['cdi'])
            if data:
                return f"{data['valor']:.2f}% acum. mês (ref: {data['data']})"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('cdi', fetch)
    
    def get_ptax_sgs(self):
        """Return the formatted PTAX from SGS."""
        def fetch():
            data = self._fetch_sgs(self.SERIES['ptax'])
            if data:
                return f"R$ {data['valor']:.4f} (ref: {data['data']})"
            return "[Dado indisponível]"
        
        return self._get_cached_or_fetch('ptax_sgs', fetch)
    
    def get_resumo_economico(self):
        """Return a summary with several indicators."""
        def fetch():
            try:
                dolar = self._fetch_dolar()
                selic = self._fetch_sgs(self.SERIES['selic_meta'])
                ipcam = self._fetch_sgs(self.SERIES['ipcam'])
                ipca12 = self._fetch_sgs(self.SERIES['ipca12'])
                cdi = self._fetch_sgs(self.SERIES['cdi'])
                
                resumo = "📊 INDICADORES ECONÔMICOS\n"
                resumo += "─" * 40 + "\n"
                
                if dolar:
                    resumo += f"💵 Dólar: R$ {dolar['venda']:.2f}\n"
                
                if selic:
                    resumo += f"📈 Selic Meta: {selic['valor']:.2f}% a.a.\n"
                
                if ipcam:
                    resumo += f"📊 IPCA Mensal: {ipcam['valor']:.2f}%\n"
                
                if ipca12:
                    resumo += f"📊 IPCA 12M: {ipca12['valor']:.2f}%\n"
                
                if cdi:
                    resumo += f"💰 CDI: {cdi['valor']:.2f}% (mês)\n"
                
                resumo += f"🕒 Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                
                return resumo
            except Exception as e:
                return f"[Erro ao gerar resumo: {str(e)}]"
        
        return self._get_cached_or_fetch('resumo', fetch)


# Standalone usage example (for manual testing)
if __name__ == "__main__":
    print("=" * 60)
    print("TESTANDO CONSULTAS À API DO BANCO CENTRAL")
    print("=" * 60)
    
    bcb = BCBConsultor()
    
    print("\n💵 Dólar:")
    print(bcb.get_dolar())
    
    print("\n📈 Selic Meta:")
    print(bcb.get_selic_meta())
    
    print("\n📊 IPCA Mensal:")
    print(bcb.get_ipca_mensal())
    
    print("\n📊 IPCA 12 Meses:")
    print(bcb.get_ipca_12m())
    
    print("\n💰 CDI:")
    print(bcb.get_cdi())
    
    print("\n💵 PTAX (SGS):")
    print(bcb.get_ptax_sgs())
    
    print("\n" + "=" * 60)
    print("RESUMO ECONÔMICO")
    print("=" * 60)
    print(bcb.get_resumo_economico())
    
    print("\n✓ Todos os testes concluídos!")