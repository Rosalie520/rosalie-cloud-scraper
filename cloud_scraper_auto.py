#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cloud_scraper_auto.py - 雲端自動爬蟲系統
部署在 Render.com，每晚 5:30 自動執行
"""

import asyncio
import json
import os
from datetime import datetime
import logging
import sys
import requests
from playwright.async_api import async_playwright

# 配置
TOKEN_SERVER = os.getenv('TOKEN_SERVER', 'https://www.rosalie.tw/AI%20Product%20Selector/api/token_manager.php')
SLACK_WEBHOOK = os.getenv('SLACK_WEBHOOK', '')

# 買手配置
AGENTS = {
    'puding': {
        'shop_id': '_dOIWWUrgz1OUw_F4kPZDjehVExH4zbXHUdfLP1w',
        'name': '布丁',
    },
    'sanmao': {
        'shop_id': '_ZZdWWzqr51tWShXc-mbVJVpa24xEhIzY',
        'name': '三毛 1號在線',
    },
    'london': {
        'shop_id': '_Z3EWWMekCLNKATBFe3tNsT1I0atNohHA',
        'name': '倫敦站',
    }
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class CloudScraper:
    """雲端爬蟲系統"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.results = {}
        
    async def start(self):
        """啟動 Playwright"""
        logger.info('🚀 初始化 Playwright...')
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        self.context = await self.browser.new_context()
        logger.info('✅ Playwright 已啟動')
        
    async def stop(self):
        """關閉 Playwright"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info('✅ Playwright 已關閉')
    
    async def fetch_all_tokens(self):
        """抓取所有買手的 Token"""
        logger.info('=' * 70)
        logger.info(f'📊 開始自動爬蟲準備 ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")})')
        logger.info('=' * 70)
        
        await self.start()
        
        try:
            for agent_key, config in AGENTS.items():
                logger.info(f'\n【{agent_key}】{config["name"]}')
                
                token = await self._fetch_token(agent_key, config['shop_id'])
                
                if token:
                    uploaded = await self._upload_token(agent_key, config['shop_id'], token)
                    
                    if uploaded:
                        verified = await self._verify_token(agent_key)
                        self.results[agent_key] = {
                            'status': 'success' if verified else 'verification_failed',
                            'token_updated': True,
                        }
                    else:
                        self.results[agent_key] = {'status': 'upload_failed'}
                else:
                    self.results[agent_key] = {'status': 'fetch_failed'}
                    
        finally:
            await self.stop()
        
        await self._generate_report()
        return self.results
    
    async def _fetch_token(self, agent_key, shop_id):
        """抓取 Token"""
        try:
            logger.info(f'   🔍 抓取 Token...')
            
            page = await self.context.new_page()
            url = f'https://www.szwego.com/static/index.html?link_type=pc_home&shop_id={shop_id}&shop_name={agent_key}'
            
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(2000)
            
            storage = await page.evaluate('''
                () => {
                    const storage = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        storage[key] = localStorage.getItem(key);
                    }
                    return storage;
                }
            ''')
            
            await page.close()
            
            token = self._extract_token(storage)
            if token:
                logger.info(f'   ✅ Token 成功 (長度: {len(token)})')
                return token
            else:
                logger.warning(f'   ❌ 未找到 token')
                return None
                
        except Exception as e:
            logger.error(f'   ❌ 抓取失敗: {str(e)}')
            return None
    
    def _extract_token(self, storage):
        """從 localStorage 提取 Token"""
        priority_keys = ['auth_token', 'access_token', 'token', 'authorization']
        
        for key in priority_keys:
            if key in storage and storage[key]:
                return storage[key]
        
        for key, value in storage.items():
            if 'token' in key.lower() and value and len(value) > 20:
                return value
        
        for key, value in storage.items():
            if value and len(value) > 50 and not key.startswith('_'):
                return value
        
        return None
    
    async def _upload_token(self, agent_key, shop_id, token):
        """上傳 Token 到伺服器"""
        try:
            logger.info(f'   📤 上傳 Token...')
            
            params = {
                'action': 'save',
                'agent_key': agent_key,
                'shop_id': shop_id,
                'token': token,
                'expires_in': 86400,
            }
            
            response = requests.post(TOKEN_SERVER, data=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    logger.info(f'   ✅ Token 已上傳')
                    return True
                else:
                    logger.warning(f'   ❌ 伺服器錯誤: {data.get("error")}')
                    return False
            else:
                logger.error(f'   ❌ HTTP {response.status_code}')
                return False
                
        except Exception as e:
            logger.error(f'   ❌ 上傳失敗: {str(e)}')
            return False
    
    async def _verify_token(self, agent_key):
        """驗證 Token"""
        try:
            logger.info(f'   🧪 驗證 Token...')
            
            url = f'{TOKEN_SERVER}?action=verify&agent_key={agent_key}'
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    logger.info(f'   ✅ Token 驗證成功')
                    return True
                else:
                    logger.warning(f'   ❌ 驗證失敗: {data.get("error")}')
                    return False
            else:
                logger.error(f'   ❌ HTTP {response.status_code}')
                return False
                
        except Exception as e:
            logger.error(f'   ❌ 驗證失敗: {str(e)}')
            return False
    
    async def _generate_report(self):
        """生成報告"""
        logger.info('\n' + '=' * 70)
        logger.info('📊 自動爬蟲準備完成')
        logger.info('=' * 70)
        
        success_count = sum(1 for r in self.results.values() if r['status'] == 'success')
        total = len(self.results)
        
        for agent_key, result in self.results.items():
            status_icon = '✅' if result['status'] == 'success' else '❌'
            logger.info(f'{status_icon} {agent_key}: {result["status"]}')
        
        logger.info(f'\n✅ 成功: {success_count}/{total}')
        logger.info('=' * 70)

async def main():
    """主函數"""
    scraper = CloudScraper()
    results = await scraper.fetch_all_tokens()
    
    if all(r['status'] == 'success' for r in results.values()):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
