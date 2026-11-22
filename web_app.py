#!/usr/bin/env python3
"""Local web dashboard (PWA-ready for iOS/macOS) for Monitor Okazji by Luis."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import monitor_okazji

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0ea5e9"/>
      <stop offset="100%" stop-color="#22c55e"/>
    </linearGradient>
  </defs>
  <rect width="128" height="128" rx="28" fill="#0b1120"/>
  <rect x="10" y="10" width="108" height="108" rx="22" fill="url(#g)" opacity="0.22"/>
  <path d="M32 68 L54 90 L98 40" fill="none" stroke="url(#g)" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="94" cy="34" r="10" fill="#f97316"/>
</svg>
"""

MANIFEST_JSON = {
    "name": "Monitor Okazji by Luis",
    "short_name": "Okazje Luis",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0b1120",
    "theme_color": "#0b1120",
    "icons": [
        {
            "src": "/icon.svg",
            "sizes": "any",
            "type": "image/svg+xml",
        }
    ],
}

HTML_PAGE = """<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="Monitor Okazji Luis" />
  <meta name="theme-color" content="#0b1120" />
  <link rel="manifest" href="/manifest.json" />
  <link rel="icon" href="/icon.svg" type="image/svg+xml" />
  <link rel="apple-touch-icon" href="/icon.svg" />
  <title>Monitor Okazji by Luis</title>
  <style>
    :root {
      --bg: #0b1120;
      --surface: #131c31;
      --surface-hover: #1b2742;
      --border: #253453;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --price-text: #4ade80;
      --discount-bg: #ef4444;
      --merchant-bg: rgba(249, 115, 22, 0.16);
      --merchant-text: #fb923c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: radial-gradient(circle at top, #172554 0%, var(--bg) 420px);
      color: var(--text);
      line-height: 1.5;
      min-height: 100vh;
    }
    .container {
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px 16px 56px;
    }
    header {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 18px;
    }
    h1 {
      margin: 0;
      font-size: 1.85rem;
      font-weight: 800;
      letter-spacing: -0.02em;
    }
    .brand-tag { color: var(--accent); font-weight: 700; }
    .subtitle { color: var(--muted); font-size: 0.92rem; margin-top: 4px; }
    .header-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .panel {
      background: rgba(19, 28, 49, 0.92);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px 16px;
      margin-bottom: 14px;
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }
    .tab-btn {
      background: var(--surface);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 8px 15px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 0.9rem;
      cursor: pointer;
    }
    .tab-btn.active {
      background: var(--accent);
      color: #082f49;
      border-color: var(--accent);
    }
    .cat-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-bottom: 14px;
    }
    .cat-pill {
      background: rgba(19, 28, 49, 0.85);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
    }
    .cat-pill.active {
      background: rgba(56, 189, 248, 0.2);
      color: var(--accent);
      border-color: var(--accent);
    }
    input[type="text"], select {
      background: #090e1a;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 10px 13px;
      font-size: 0.94rem;
    }
    input[type="text"] { flex: 1 1 220px; }
    button {
      background: var(--accent);
      color: #082f49;
      border: none;
      border-radius: 9px;
      padding: 10px 16px;
      font-size: 0.92rem;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover { background: #7dd3fc; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-secondary {
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
    }
    .btn-secondary:hover { background: var(--surface-hover); }
    .btn-small {
      padding: 5px 10px;
      font-size: 0.78rem;
      border-radius: 7px;
    }
    .btn-notify.active {
      background: rgba(34, 197, 94, 0.18);
      color: var(--price-text);
      border-color: rgba(74, 222, 128, 0.5);
    }
    .fav-btn {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 0.82rem;
      cursor: pointer;
    }
    .fav-btn.saved {
      color: #facc15;
      border-color: rgba(250, 204, 21, 0.5);
      background: rgba(250, 204, 21, 0.12);
    }
    .sources-list {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-top: 10px;
      font-size: 0.88rem;
    }
    .sources-list label, .inline-toggle {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      color: var(--text);
      font-size: 0.9rem;
    }
    .status-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
      margin: 12px 0 14px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    .pagination-bar {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin: 14px 0;
      padding: 10px 14px;
      background: rgba(19, 28, 49, 0.82);
      border: 1px solid var(--border);
      border-radius: 12px;
      font-size: 0.9rem;
    }
    .pagination-btns {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .error-box {
      background: rgba(245, 158, 11, 0.12);
      border: 1px solid rgba(245, 158, 11, 0.4);
      color: #fde68a;
      padding: 12px 14px;
      border-radius: 10px;
      margin-bottom: 18px;
      font-size: 0.9rem;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(315px, 1fr));
      gap: 16px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: transform 0.14s ease, border-color 0.14s ease, background 0.14s ease;
    }
    .card:hover {
      background: var(--surface-hover);
      border-color: #3b82f6;
      transform: translateY(-2px);
    }
    .thumb-wrap {
      position: relative;
      height: 178px;
      background: #ffffff;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      border-bottom: 1px solid var(--border);
      text-decoration: none;
    }
    .thumb-wrap.no-img {
      background: linear-gradient(135deg, #172554, #1e293b);
      color: var(--muted);
      font-size: 0.88rem;
    }
    .thumb-wrap img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      padding: 10px;
    }
    .discount-pill {
      position: absolute;
      top: 10px;
      left: 10px;
      background: var(--discount-bg);
      color: #ffffff;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.85rem;
      font-weight: 800;
      box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
    }
    .price-pill {
      position: absolute;
      bottom: 10px;
      right: 10px;
      background: rgba(15, 23, 42, 0.94);
      color: var(--price-text);
      border: 1px solid rgba(74, 222, 128, 0.45);
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.92rem;
      font-weight: 800;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }
    .old-price {
      color: #94a3b8;
      text-decoration: line-through;
      font-size: 0.78rem;
      font-weight: 600;
    }
    .card-body {
      padding: 14px 16px 16px;
      display: flex;
      flex-direction: column;
      gap: 9px;
      flex: 1;
    }
    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }
    .badge {
      display: inline-block;
      padding: 2px 9px;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
    }
    .badge.merchant {
      background: var(--merchant-bg);
      color: var(--merchant-text);
    }
    .badge.cat {
      background: rgba(148, 163, 184, 0.16);
      color: #cbd5e1;
      font-weight: 500;
    }
    .verdict {
      font-size: 0.8rem;
      font-weight: 700;
      padding: 5px 9px;
      border-radius: 8px;
      background: rgba(56, 189, 248, 0.12);
      color: var(--accent);
      border: 1px solid rgba(56, 189, 248, 0.35);
    }
    .verdict.cheapest {
      background: rgba(34, 197, 94, 0.16);
      color: #4ade80;
      border-color: rgba(74, 222, 128, 0.45);
    }
    .verdict.cheaper_elsewhere {
      background: rgba(245, 158, 11, 0.15);
      color: #fbbf24;
      border-color: rgba(245, 158, 11, 0.45);
    }
    .card a.title {
      color: var(--text);
      text-decoration: none;
      font-weight: 700;
      font-size: 1rem;
      line-height: 1.35;
    }
    .card a.title:hover { color: var(--accent); text-decoration: underline; }
    .summary {
      color: var(--muted);
      font-size: 0.85rem;
      margin: 0;
      flex: 1;
    }
    .history-box {
      background: rgba(9, 14, 26, 0.75);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 7px 10px;
      font-size: 0.8rem;
    }
    .history-box summary {
      cursor: pointer;
      color: #cbd5e1;
      font-weight: 600;
    }
    .history-list {
      margin: 6px 0 6px;
      padding-left: 16px;
      color: var(--muted);
    }
    .history-list li { margin-bottom: 2px; }
    .history-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-top: 6px;
    }
    .history-ext {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }
    .history-ext:hover { text-decoration: underline; }
    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      font-size: 0.78rem;
      color: var(--muted);
      padding-top: 6px;
      border-top: 1px solid rgba(51, 65, 85, 0.55);
    }
    .go-link {
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
      white-space: nowrap;
    }
    .go-link:hover { text-decoration: underline; }
    .empty {
      grid-column: 1 / -1;
      text-align: center;
      color: var(--muted);
      padding: 48px 16px;
      background: var(--surface);
      border-radius: 14px;
      border: 1px solid var(--border);
    }
    @media (max-width: 600px) {
      .grid { grid-template-columns: 1fr; }
      h1 { font-size: 1.5rem; }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Monitor Okazji <span class="brand-tag">by Luis</span></h1>
        <div class="subtitle">Bezpośrednie promocje ze sklepów i porównanie cen — od największych okazji od góry</div>
      </div>
      <div class="header-actions">
        <button id="notifyBtn" class="btn-secondary btn-notify" onclick="toggleNotifications()">Włącz powiadomienia</button>
        <label class="inline-toggle">
          <input id="autoRefreshCheck" type="checkbox" onchange="toggleAutoRefresh()" />
          Auto co 5 min
        </label>
        <button id="scanBtn" onclick="runScan()">Odśwież skan</button>
      </div>
    </header>

    <div class="tabs">
      <button id="tabProducts" class="tab-btn active" onclick="setViewMode('products')">Produkty i promocje</button>
      <button id="tabLeaflets" class="tab-btn" onclick="setViewMode('leaflets')">Gazetki (Biedronka.pl)</button>
      <button id="tabSaved" class="tab-btn" onclick="setViewMode('saved')">Zapisane (0)</button>
      <button id="tabAll" class="tab-btn" onclick="setViewMode('all')">Wszystko</button>
    </div>

    <div id="categoryPills" class="cat-pills"></div>

    <div class="panel">
      <div class="row">
        <input id="keywordsInput" type="text" placeholder="Słowa kluczowe po przecinku (puste = wszystkie), np. kawa, lego, kurtka, wiertarka" />
        <button onclick="saveConfigAndScan()">Zapisz filtry i skanuj</button>
      </div>
      <div id="sourcesCheckboxes" class="sources-list"></div>
    </div>

    <div class="panel">
      <div class="row">
        <input id="searchInput" type="text" placeholder="Szukaj na liście (produkt, sklep, kategoria)..." oninput="resetPageAndRender()" />
        <select id="sourceFilter" onchange="resetPageAndRender()">
          <option value="">Wszystkie sklepy</option>
        </select>
        <select id="discountFilter" onchange="resetPageAndRender()">
          <option value="0">Każdy rabat</option>
          <option value="20">Rabat od -20%</option>
          <option value="40">Rabat od -40%</option>
          <option value="60">Rabat od -60%</option>
          <option value="cheapest">Tylko najtaniej na Ceneo</option>
        </select>
        <select id="sortSelect" onchange="resetPageAndRender()">
          <option value="best">Największe okazje od góry</option>
          <option value="savings">Największa oszczędność (zł)</option>
          <option value="newest">Kolejność ze źródeł</option>
        </select>
        <select id="pageSizeSelect" onchange="resetPageAndRender()" title="Ile pozycji na stronie">
          <option value="15">15 / str.</option>
          <option value="20" selected>20 / str.</option>
          <option value="25">25 / str.</option>
          <option value="35">35 / str.</option>
          <option value="9999">Wszystkie</option>
        </select>
        <button class="btn-secondary" onclick="clearFilters()">Wyczyść</button>
      </div>
    </div>

    <div id="statusBar" class="status-bar">Ładowanie...</div>
    <div id="errorBox" class="error-box" style="display:none;"></div>
    <div id="paginationTop" class="pagination-bar" style="display:none;"></div>
    <div id="dealsContainer" class="grid"></div>
    <div id="paginationBottom" class="pagination-bar" style="display:none;"></div>
  </div>

  <script>
    let allDeals = [];
    let currentConfig = { sources: [], keywords: [] };
    let knownIds = new Set();
    let autoTimer = null;
    let viewMode = 'products';
    let activeGroup = '';
    let currentPage = 1;
    let savedIds = new Set(JSON.parse(localStorage.getItem('luis_saved_deals') || '[]'));

    function classifyGroup(d) {
      if (d.is_leaflet) return 'Gazetki';
      const txt = [d.category, d.title, d.merchant].filter(Boolean).join(' ').toLowerCase();
      if (/odzież|ubrani|obuwi|buty|sneakers|kurtk|koszul|spodnie|piżam|sukien|uroda|perfum|krem|szampon|rossmann|droger|makijaż/.test(txt)) return 'Odzież i uroda';
      if (/budowlan|narzędzi|warsztat|wiertark|kosiark|castorama|ogród|dom i warsztat|mebl|szafa|odkurzacz|robot sprzątaj|pościel|lampa|kuchni/.test(txt)) return 'Budowlane i dom';
      if (/spożywcz|jedzen|kawa|herbata|lody|napoje|dino|lidl\.pl|mleko|masło|mięso|pieczark|czekolad|ser\b/.test(txt)) return 'Spożywcze i markety';
      if (/smyk|lego|zabawk|dziec|klocki|gry planszowe|wózek|fotelik/.test(txt)) return 'Dzieci i zabawki';
      if (/elektronik|słuchawk|tv|telewizor|laptop|monitor|smartfon|iphone|ssd|dysk|dac|projektor|ładowark|usb|kamera|audio|głośnik|soundbar|powerbank/.test(txt)) return 'Elektronika i okazje';
      if (d.store_group) return d.store_group;
      return 'Inne';
    }

    function toggleSaved(dealId) {
      if (savedIds.has(dealId)) savedIds.delete(dealId);
      else savedIds.add(dealId);
      localStorage.setItem('luis_saved_deals', JSON.stringify([...savedIds]));
      updateSavedTabCount();
      renderDeals();
    }

    function updateSavedTabCount() {
      const count = allDeals.filter(d => savedIds.has(d.deal_id)).length;
      document.getElementById('tabSaved').textContent = `Zapisane (${count})`;
    }

    function setGroupFilter(groupName) {
      activeGroup = groupName;
      currentPage = 1;
      renderCategoryPills();
      renderDeals();
    }

    function renderCategoryPills() {
      const box = document.getElementById('categoryPills');
      if (viewMode === 'leaflets') {
        box.innerHTML = '';
        return;
      }
      const base = modeFilteredDeals();
      const counts = {};
      base.forEach(d => {
        const g = classifyGroup(d);
        counts[g] = (counts[g] || 0) + 1;
      });
      const order = [
        'Odzież i uroda',
        'Spożywcze i markety',
        'Budowlane i dom',
        'Elektronika i okazje',
        'Dzieci i zabawki',
        'Inne'
      ];
      const pills = [`<button class="cat-pill ${activeGroup === '' ? 'active' : ''}" onclick="setGroupFilter('')">Wszystkie (${base.length})</button>`];
      order.forEach(g => {
        if (counts[g]) {
          pills.push(`<button class="cat-pill ${activeGroup === g ? 'active' : ''}" onclick="setGroupFilter('${g}')">${g} (${counts[g]})</button>`);
        }
      });
      box.innerHTML = pills.join('');
    }

    function setViewMode(mode) {
      viewMode = mode;
      activeGroup = '';
      currentPage = 1;
      document.getElementById('tabProducts').classList.toggle('active', mode === 'products');
      document.getElementById('tabLeaflets').classList.toggle('active', mode === 'leaflets');
      document.getElementById('tabSaved').classList.toggle('active', mode === 'saved');
      document.getElementById('tabAll').classList.toggle('active', mode === 'all');
      document.getElementById('sourceFilter').value = '';
      updateSourceDropdown();
      renderCategoryPills();
      renderDeals();
    }

    function resetPageAndRender() {
      currentPage = 1;
      renderDeals();
    }

    function changePage(newPage) {
      currentPage = newPage;
      renderDeals();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function updateNotifyButton() {
      const btn = document.getElementById('notifyBtn');
      if (!('Notification' in window)) {
        btn.textContent = 'Brak powiadomień w przeglądarce';
        btn.disabled = true;
        return;
      }
      if (Notification.permission === 'granted') {
        btn.textContent = 'Powiadomienia włączone';
        btn.classList.add('active');
      } else if (Notification.permission === 'denied') {
        btn.textContent = 'Powiadomienia zablokowane';
      } else {
        btn.textContent = 'Włącz powiadomienia';
        btn.classList.remove('active');
      }
    }

    async function toggleNotifications() {
      if (!('Notification' in window)) return;
      const perm = await Notification.requestPermission();
      updateNotifyButton();
      if (perm === 'granted') {
        new Notification('Monitor Okazji by Luis', {
          body: 'Powiadomienia o nowych okazjach zostały włączone.'
        });
      }
    }

    function toggleAutoRefresh() {
      const checked = document.getElementById('autoRefreshCheck').checked;
      if (autoTimer) {
        clearInterval(autoTimer);
        autoTimer = null;
      }
      if (checked) {
        autoTimer = setInterval(runScan, 5 * 60 * 1000);
      }
    }

    async function loadConfig() {
      const res = await fetch('/api/config');
      currentConfig = await res.json();
      document.getElementById('keywordsInput').value = (currentConfig.keywords || []).join(', ');
      const box = document.getElementById('sourcesCheckboxes');
      box.innerHTML = (currentConfig.sources || []).map((s, idx) => `
        <label>
          <input type="checkbox" data-source-idx="${idx}" ${s.enabled ? 'checked' : ''} />
          ${escapeHtml(s.name)}
        </label>
      `).join('');
    }

    async function saveConfigAndScan() {
      const raw = document.getElementById('keywordsInput').value;
      const keywords = raw.split(',').map(k => k.trim()).filter(Boolean);
      const checkboxes = document.querySelectorAll('#sourcesCheckboxes input[type="checkbox"]');
      checkboxes.forEach(cb => {
        const idx = Number(cb.dataset.sourceIdx);
        if (currentConfig.sources[idx]) {
          currentConfig.sources[idx].enabled = cb.checked;
        }
      });
      currentConfig.keywords = keywords;

      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentConfig)
      });
      await runScan();
    }

    async function loadCached() {
      updateNotifyButton();
      await loadConfig();
      const res = await fetch('/api/deals');
      const data = await res.json();
      (data.deals || []).forEach(d => knownIds.add(d.deal_id));
      applyData(data, false);
    }

    async function runScan() {
      const btn = document.getElementById('scanBtn');
      const status = document.getElementById('statusBar');
      btn.disabled = true;
      btn.textContent = 'Skanowanie...';
      status.textContent = 'Pobieranie ofert bezpośrednio ze sklepów i porównywanie cen...';
      try {
        const res = await fetch('/api/scan', { method: 'POST' });
        const data = await res.json();
        applyData(data, true);
      } catch (err) {
        status.textContent = 'Błąd podczas skanowania: ' + err;
      } finally {
        btn.disabled = false;
        btn.textContent = 'Odśwież skan';
      }
    }

    async function compareDeal(dealId, btnEl) {
      const idx = allDeals.findIndex(d => d.deal_id === dealId);
      if (idx === -1) return;
      const deal = allDeals[idx];
      btnEl.disabled = true;
      btnEl.textContent = 'Sprawdzam sklepy...';
      try {
        const res = await fetch('/api/compare', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ deal_id: deal.deal_id, title: deal.title, price: deal.price || '' })
        });
        const data = await res.json();
        if (data.deal) {
          allDeals[idx] = data.deal;
          renderDeals();
        } else {
          btnEl.textContent = data.message || 'Nie znaleziono na Ceneo';
        }
      } catch (err) {
        btnEl.textContent = 'Błąd porównania';
      }
    }

    function modeFilteredDeals() {
      if (viewMode === 'products') return allDeals.filter(d => !d.is_leaflet);
      if (viewMode === 'leaflets') return allDeals.filter(d => Boolean(d.is_leaflet));
      if (viewMode === 'saved') return allDeals.filter(d => savedIds.has(d.deal_id));
      return allDeals;
    }

    function updateSourceDropdown() {
      const select = document.getElementById('sourceFilter');
      const current = select.value;
      const visible = modeFilteredDeals();
      const sources = [...new Set(visible.map(d => d.source))];
      select.innerHTML = '<option value="">Wszystkie sklepy</option>' +
        sources.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
      if (sources.includes(current)) select.value = current;
    }

    function applyData(data, notifyIfNew) {
      const incoming = data.deals || [];
      if (notifyIfNew && knownIds.size > 0 && 'Notification' in window && Notification.permission === 'granted') {
        const fresh = incoming.filter(d => !knownIds.has(d.deal_id) && !d.is_leaflet);
        if (fresh.length > 0) {
          const top = fresh[0];
          new Notification(`Nowe okazje (${fresh.length}) — Monitor Okazji by Luis`, {
            body: `${top.title}${top.price ? ' • ' + top.price : ''}`
          });
        }
      }
      incoming.forEach(d => knownIds.add(d.deal_id));
      allDeals = incoming;
      currentPage = 1;

      updateSourceDropdown();
      updateSavedTabCount();
      renderCategoryPills();

      const productCount = allDeals.filter(d => !d.is_leaflet).length;
      const leafletCount = allDeals.filter(d => Boolean(d.is_leaflet)).length;
      document.getElementById('tabProducts').textContent = `Produkty i promocje (${productCount})`;
      document.getElementById('tabLeaflets').textContent = `Gazetki Biedronka (${leafletCount})`;
      document.getElementById('tabAll').textContent = `Wszystko (${allDeals.length})`;

      const status = document.getElementById('statusBar');
      const activeKeywords = (currentConfig.keywords || []).length
        ? currentConfig.keywords.join(', ')
        : 'brak (wszystkie)';
      status.innerHTML =
        `Ostatnia aktualizacja: <strong>${escapeHtml(data.updated_at || 'brak')}</strong> ` +
        `&bull; Produktów: <strong>${productCount}</strong> ` +
        `&bull; Gazetek: <strong>${leafletCount}</strong> ` +
        `&bull; Filtry: <strong>${escapeHtml(activeKeywords)}</strong>`;

      const errBox = document.getElementById('errorBox');
      if (data.errors && data.errors.length > 0) {
        errBox.style.display = 'block';
        errBox.innerHTML = '<strong>Uwagi pobierania:</strong><br>' + data.errors.map(escapeHtml).join('<br>');
      } else {
        errBox.style.display = 'none';
      }

      renderDeals();
    }

    function renderPaginationBars(totalItems, pageSize) {
      const topBar = document.getElementById('paginationTop');
      const botBar = document.getElementById('paginationBottom');
      const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
      if (currentPage > totalPages) currentPage = totalPages;

      if (totalItems === 0 || pageSize >= 9999 || totalPages <= 1) {
        const info = totalItems > 0 ? `Wyświetlono <strong>${totalItems}</strong> z <strong>${totalItems}</strong> pozycji` : '';
        if (info) {
          topBar.style.display = 'flex';
          topBar.innerHTML = `<span>${info}</span>`;
        } else {
          topBar.style.display = 'none';
        }
        botBar.style.display = 'none';
        return;
      }

      const startIdx = (currentPage - 1) * pageSize + 1;
      const endIdx = Math.min(totalItems, currentPage * pageSize);
      const html = `
        <span>Pozycje <strong>${startIdx}–${endIdx}</strong> z <strong>${totalItems}</strong> &bull; Strona <strong>${currentPage}</strong> z <strong>${totalPages}</strong></span>
        <div class="pagination-btns">
          <button class="btn-secondary btn-small" ${currentPage <= 1 ? 'disabled' : ''} onclick="changePage(${currentPage - 1})">&larr; Poprzednia</button>
          <button class="btn-secondary btn-small" ${currentPage >= totalPages ? 'disabled' : ''} onclick="changePage(${currentPage + 1})">Następna &rarr;</button>
        </div>
      `;
      topBar.style.display = 'flex';
      topBar.innerHTML = html;
      botBar.style.display = 'flex';
      botBar.innerHTML = html;
    }

    function buildCleanQuery(title) {
      return String(title || '')
        .replace(/\[[^\]]*\]|\([^)]*\)/g, ' ')
        .replace(/\b(za|od|tylko|jedyne|cena|kat\.?|zamiast|promocja|wyprzedaż|black\s*friday|weekend|rabat\w*|taniej|amazon\w*|allegro|x-kom|empik|dino|lidl|biedronka|smyk|rossmann|castorama)\b/gi, ' ')
        .replace(/\d[\d\s.,]*\s*(?:zł|pln|€|\$)/gi, ' ')
        .trim()
        .split(/\s+/)
        .filter(w => w.length >= 2)
        .slice(0, 5)
        .join(' ');
    }

    function renderDeals() {
      const q = document.getElementById('searchInput').value.trim().toLowerCase();
      const src = document.getElementById('sourceFilter').value;
      const discMin = document.getElementById('discountFilter').value;
      const sortMode = document.getElementById('sortSelect').value;
      const pageSize = Number(document.getElementById('pageSizeSelect').value || 20);

      let filtered = modeFilteredDeals().filter(d => {
        if (src && d.source !== src) return false;
        if (activeGroup && classifyGroup(d) !== activeGroup) return false;
        if (discMin === 'cheapest' && d.price_status !== 'cheapest') return false;
        if (discMin !== 'cheapest' && Number(discMin) > 0 && (d.discount_pct || 0) < Number(discMin)) return false;
        if (!q) return true;
        return [d.title, d.summary, d.merchant, d.category, d.store_group, d.price, d.price_verdict]
          .filter(Boolean).join(' ').toLowerCase().includes(q);
      });

      if (sortMode === 'best') {
        filtered = [...filtered].sort((a, b) =>
          (b.deal_score || 0) - (a.deal_score || 0) ||
          (b.discount_pct || 0) - (a.discount_pct || 0) ||
          (b.savings_pln || 0) - (a.savings_pln || 0)
        );
      } else if (sortMode === 'savings') {
        filtered = [...filtered].sort((a, b) =>
          (b.savings_pln || 0) - (a.savings_pln || 0) ||
          (b.discount_pct || 0) - (a.discount_pct || 0)
        );
      }

      renderPaginationBars(filtered.length, pageSize);

      const container = document.getElementById('dealsContainer');
      if (filtered.length === 0) {
        container.innerHTML = '<div class="empty">Brak pozycji w tym widoku. Zmień filtry, przełącz zakładkę lub kliknij <strong>Odśwież skan</strong>.</div>';
        return;
      }

      const start = (currentPage - 1) * pageSize;
      const pageItems = pageSize >= 9999 ? filtered : filtered.slice(start, start + pageSize);

      container.innerHTML = pageItems.map(d => {
        const discountLabel = d.discount_pct === 100
          ? 'GRATIS'
          : (d.discount_pct > 0 ? `-${d.discount_pct}%` : (d.savings_pln > 0 ? `-${Math.round(d.savings_pln)} zł` : ''));
        const discountBadge = discountLabel ? `<span class="discount-pill">${escapeHtml(discountLabel)}</span>` : '';

        const priceHtml = d.price
          ? `<span class="price-pill">${d.old_price ? `<span class="old-price">${escapeHtml(d.old_price)}</span>` : ''}${escapeHtml(d.price)}</span>`
          : '';

        const imgBlock = d.image_url
          ? `<a class="thumb-wrap" href="${escapeHtml(d.link)}" target="_blank" rel="noopener noreferrer">${discountBadge}<img src="${escapeHtml(d.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />${priceHtml}</a>`
          : `<a class="thumb-wrap no-img" href="${escapeHtml(d.link)}" target="_blank" rel="noopener noreferrer">${discountBadge}<span>${escapeHtml(d.source)}</span>${priceHtml}</a>`;

        const verdictBlock = d.price_verdict
          ? `<div class="verdict ${escapeHtml(d.price_status || '')}">${escapeHtml(d.price_verdict)}</div>`
          : '';

        const historyEntries = Array.isArray(d.price_history) ? d.price_history : [];
        const cleanQ = buildCleanQuery(d.title) || d.title.slice(0, 50);
        const ceneoUrl = d.ceneo_url || `https://www.ceneo.pl/;szukaj-${encodeURIComponent(cleanQ).replace(/%20/g, '+')}`;
        const pepperArchiveUrl = `https://www.pepper.pl/search?q=${encodeURIComponent(cleanQ)}`;

        const historyBlock = !d.is_leaflet
          ? `<details class="history-box">
               <summary>Archiwum i porównanie cen (${historyEntries.length})</summary>
               ${d.lowest_30d ? `<div style="margin-top:4px;color:#cbd5e1;">Najniższa z 30 dni (Omnibus): <strong>${escapeHtml(d.lowest_30d)}</strong></div>` : ''}
               ${historyEntries.length > 0
                 ? `<ul class="history-list">${historyEntries.map(h => `<li><strong>${escapeHtml(h.price)}</strong> — ${escapeHtml(h.note || '')} (${escapeHtml(h.date)})</li>`).join('')}</ul>`
                 : `<div style="margin-top:4px;color:var(--muted);">Brak zapisanych wcześniejszych notowań. Kolejne skany zbudują historię.</div>`}
               <div class="history-actions">
                 <button class="btn-secondary btn-small" onclick='compareDeal(${JSON.stringify(d.deal_id)}, this)'>Porównaj w sklepach (Ceneo)</button>
                 <a class="history-ext" href="${escapeHtml(ceneoUrl)}" target="_blank" rel="noopener noreferrer">Ceneo &rarr;</a>
                 <a class="history-ext" href="${escapeHtml(pepperArchiveUrl)}" target="_blank" rel="noopener noreferrer">Archiwum Pepper &rarr;</a>
               </div>
             </details>`
          : '';

        return `
          <article class="card">
            ${imgBlock}
            <div class="card-body">
              <div class="badges">
                <span class="badge">${escapeHtml(d.source)}</span>
                ${d.merchant ? `<span class="badge merchant">${escapeHtml(d.merchant)}</span>` : ''}
                <span class="badge cat">${escapeHtml(classifyGroup(d))}</span>
              </div>
              ${verdictBlock}
              <a class="title" href="${escapeHtml(d.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(d.title)}</a>
              ${d.summary ? `<p class="summary">${escapeHtml(d.summary)}</p>` : ''}
              ${historyBlock}
              <div class="card-footer">
                <span>${escapeHtml(d.published || '')}</span>
                <div style="display:flex;gap:8px;align-items:center;">
                  <button class="fav-btn ${savedIds.has(d.deal_id) ? 'saved' : ''}" onclick='toggleSaved(${JSON.stringify(d.deal_id)})' title="Zapisz na później">${savedIds.has(d.deal_id) ? '★ Zapisane' : '☆ Zapisz'}</button>
                  <a class="go-link" href="${escapeHtml(d.link)}" target="_blank" rel="noopener noreferrer">Otwórz &rarr;</a>
                </div>
              </div>
            </div>
          </article>
        `;
      }).join('');
    }

    function clearFilters() {
      document.getElementById('searchInput').value = '';
      document.getElementById('sourceFilter').value = '';
      document.getElementById('discountFilter').value = '0';
      document.getElementById('sortSelect').value = 'best';
      document.getElementById('pageSizeSelect').value = '20';
      activeGroup = '';
      currentPage = 1;
      renderCategoryPills();
      renderDeals();
    }

    function escapeHtml(str) {
      return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    loadCached();
  </script>
</body>
</html>
"""


def _read_cached_deals(config_path: Path) -> dict[str, Any]:
    """Read latest cached deals JSON generated by monitor_okazji."""
    config = monitor_okazji.load_config(config_path)
    cache_path = config_path.parent / config.get("cache_file", "latest_deals.json")
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"updated_at": "brak zapisanych danych", "deals": [], "errors": []}


def _perform_live_scan(config_path: Path) -> dict[str, Any]:
    """Fetch all enabled feeds and direct stores, update history/cache, and return JSON."""
    base_dir = config_path.parent
    config = monitor_okazji.load_config(config_path)
    keywords = [str(k).strip() for k in config.get("keywords", []) if str(k).strip()]

    seen_path = base_dir / config.get("seen_file", "seen_deals.json")
    csv_path = base_dir / config.get("csv_file", "historia_okazji.csv")
    report_path = base_dir / config.get("report_file", "raport_okazji.md")
    cache_path = base_dir / config.get("cache_file", "latest_deals.json")
    history_path = base_dir / config.get("price_history_file", "price_history.json")

    seen_ids = monitor_okazji.load_seen_ids(seen_path)
    all_deals, errors = monitor_okazji.fetch_all_sources(config)
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    all_deals = monitor_okazji.update_and_attach_price_history(history_path, all_deals, timestamp)

    auto_compare_n = int(config.get("auto_compare_top_n", 0))
    if auto_compare_n > 0:
        all_deals = monitor_okazji.enrich_deals_with_ceneo(
            all_deals, history_path, timestamp, max_compare=auto_compare_n
        )

    new_deals: list[monitor_okazji.Deal] = []
    for deal in all_deals:
        if deal.deal_id not in seen_ids:
            new_deals.append(deal)
            seen_ids.add(deal.deal_id)

    report = monitor_okazji.render_markdown_report(
        all_deals, errors, keywords, timestamp, only_new=False
    )
    report_path.write_text(report, encoding="utf-8")
    monitor_okazji.append_csv(csv_path, new_deals, timestamp)
    monitor_okazji.save_seen_ids(seen_path, seen_ids)
    monitor_okazji.save_latest_cache(cache_path, all_deals, errors, timestamp)
    monitor_okazji.send_notifications(new_deals, config)

    return {
        "updated_at": timestamp,
        "deals": [dataclasses.asdict(d) for d in all_deals],
        "errors": errors,
    }


def _compare_single_deal(config_path: Path, deal_id: str, title: str, price: str) -> dict[str, Any]:
    """Compare a single deal against Ceneo and persist updated history/cache."""
    base_dir = config_path.parent
    config = monitor_okazji.load_config(config_path)
    cache_path = base_dir / config.get("cache_file", "latest_deals.json")
    history_path = base_dir / config.get("price_history_file", "price_history.json")

    res = monitor_okazji.compare_product_on_ceneo(title, price)
    if not res.get("matched"):
        return {"matched": False, "message": "Brak dopasowania na Ceneo"}

    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    cache = _read_cached_deals(config_path)
    deals_list = cache.get("deals", [])
    history_map = monitor_okazji.load_price_history(history_path)

    updated_deal_dict: dict[str, Any] | None = None
    for item in deals_list:
        if item.get("deal_id") == deal_id:
            deal_obj = monitor_okazji.Deal(**{
                k: v for k, v in item.items() if k in {f.name for f in dataclasses.fields(monitor_okazji.Deal)}
            })
            key = monitor_okazji.product_key(deal_obj)
            entries = list(history_map.get(key, item.get("price_history", [])))
            existing = {(e.get("date"), e.get("note"), e.get("price")) for e in entries}
            for off in res.get("offers", []):
                tup = (timestamp, f"Ceneo: {off['shop']}", off["price"])
                if tup not in existing:
                    entries.append({"date": timestamp, "price": off["price"], "note": f"Ceneo: {off['shop']}"})
                    existing.add(tup)
            if not res.get("offers") and res.get("ceneo_min"):
                tup = (timestamp, "Ceneo (najniższa)", res["ceneo_min"])
                if tup not in existing:
                    entries.append({"date": timestamp, "price": res["ceneo_min"], "note": "Ceneo (najniższa)"})
            entries = entries[-20:]
            history_map[key] = entries

            item["ceneo_url"] = res.get("ceneo_url", item.get("ceneo_url", ""))
            item["price_status"] = res.get("status", "")
            item["price_verdict"] = res.get("verdict", "")
            item["compared_offers"] = res.get("offers", [])
            item["price_history"] = entries
            updated_deal_dict = item
            break

    if updated_deal_dict is not None:
        history_path.write_text(json.dumps(history_map, ensure_ascii=False, indent=2), encoding="utf-8")
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"matched": True, "deal": updated_deal_dict, "comparison": res}


def make_handler(config_path: Path) -> type[BaseHTTPRequestHandler]:
    """Bind config_path to the HTTP request handler."""

    class DealHandler(BaseHTTPRequestHandler):
        def _send_bytes(self, body: bytes, content_type: str, status: int = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            self._send_bytes(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
                status=status,
            )

        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                self._send_bytes(HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/manifest.json":
                self._send_json(MANIFEST_JSON)
                return
            if path == "/icon.svg":
                self._send_bytes(ICON_SVG.encode("utf-8"), "image/svg+xml")
                return
            if path == "/api/deals":
                self._send_json(_read_cached_deals(config_path))
                return
            if path == "/api/config":
                self._send_json(monitor_okazji.load_config(config_path))
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/scan":
                self._send_json(_perform_live_scan(config_path))
                return
            if path == "/api/compare":
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                result = _compare_single_deal(
                    config_path,
                    str(body.get("deal_id", "")),
                    str(body.get("title", "")),
                    str(body.get("price", "")),
                )
                self._send_json(result)
                return
            if path == "/api/config":
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                updated = json.loads(body)
                config = monitor_okazji.load_config(config_path)
                if isinstance(updated.get("keywords"), list):
                    config["keywords"] = [
                        str(k).strip() for k in updated["keywords"] if str(k).strip()
                    ]
                if isinstance(updated.get("sources"), list):
                    config["sources"] = updated["sources"]
                config_path.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                self._send_json(config)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return DealHandler


class IPv6HTTPServer(ThreadingHTTPServer):
    """HTTP server bound explicitly to IPv6 loopback."""

    address_family = socket.AF_INET6


def create_servers(host: str, port: int, config_path: Path) -> list[ThreadingHTTPServer]:
    """Create loopback servers for both IPv4 (127.0.0.1) and IPv6 (::1)."""
    handler = make_handler(config_path)
    if host in ("loopback", "localhost", "::", ""):
        servers: list[ThreadingHTTPServer] = [
            ThreadingHTTPServer(("127.0.0.1", port), handler)
        ]
        try:
            servers.append(IPv6HTTPServer(("::1", port), handler))
        except OSError:
            pass
        return servers
    return [ThreadingHTTPServer((host, port), handler)]


def main() -> int:
    """Start the local web dashboard server."""
    parser = argparse.ArgumentParser(description="Lokalny interfejs webowy Monitor Okazji by Luis.")
    parser.add_argument("--config", default="config.json", help="Ścieżka do config.json")
    parser.add_argument(
        "--host",
        default="loopback",
        help="Adres nasłuchu (domyślnie loopback: 127.0.0.1 oraz ::1; użyj 0.0.0.0 dla dostępu z iPhone'a w Wi-Fi)",
    )
    parser.add_argument("--port", type=int, default=8765, help="Port serwera (domyślnie 8765)")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    servers = create_servers(args.host, args.port, config_path)
    for extra_server in servers[1:]:
        thread = threading.Thread(target=extra_server.serve_forever, daemon=True)
        thread.start()

    print(
        f"Monitor Okazji by Luis działa pod adresem: http://localhost:{args.port} (oraz http://127.0.0.1:{args.port})",
        flush=True,
    )
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        print("\nZamykanie serwera...")
        for srv in servers:
            srv.shutdown()
            srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
