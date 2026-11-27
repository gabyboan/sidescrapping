(() => {
  'use strict';

  const SOURCE = 'https://raw.githubusercontent.com/gabyboan/sidescrapping/main/catalogo.json';
  const OTHER_SOURCE = 'https://raw.githubusercontent.com/gabyboan/sidescrapping/main/supermercados.json';
  const MARKET_SOURCE = 'https://raw.githubusercontent.com/gabyboan/sidescrapping/main/mercado.json';
  const COMPARISON_SOURCES = ['comparaciones.json', 'comparaciones_side.json'].map(name => `https://raw.githubusercontent.com/gabyboan/sidescrapping/main/${name}`);
  const PAGE_SIZE = 24;
  // Plan 7: expire at midnight in Argentina after the published end date.
  const installmentPromoActive = Date.now() >= Date.parse('2026-01-01T03:00:00Z') && Date.now() < Date.parse('2027-01-01T03:00:00Z');
  const $ = id => document.getElementById(id);
  $('installmentPromo').hidden = !installmentPromoActive;
  const els = Object.fromEntries(['search','origin','category','merchant','sort','products','status','pagination','resultCount','totalMetric','discountMetric','updatedMetric','updatedDetail','sourceCoverage'].map(id => [id, $(id)]));
  const state = {products: [], comparisons: {}, filter: 'deal', page: 1, loadingOptional: true};
  let comparisonCache = new WeakMap();
  let referenceIndex = new Set();
  let filteredCache = null;
  let filteredUntil = 0;
  const referenceKey = (ean, url, origin, price) => JSON.stringify([ean, url, origin, price]);
  function invalidateData() {
    comparisonCache = new WeakMap();
    filteredCache = null;
    referenceIndex = new Set(state.products.filter(p => p.disponible === true && p.ean).map(p => referenceKey(p.ean, p.url, p.origen, p.precio_vigente_centavos)));
  }
  const number = new Intl.NumberFormat('es-AR');
  const currencyWhole = new Intl.NumberFormat('es-AR', {style:'currency', currency:'ARS', minimumFractionDigits:0, maximumFractionDigits:2});
  const currencyCents = new Intl.NumberFormat('es-AR', {style:'currency', currency:'ARS', minimumFractionDigits:2, maximumFractionDigits:2});
  const percentFormat = new Intl.NumberFormat('es-AR', {maximumFractionDigits:1});
  const dateFormat = new Intl.DateTimeFormat('es-AR', {timeZone:'America/Argentina/Buenos_Aires', day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'});
  const money = cents => typeof cents === 'number' && Number.isFinite(cents) && cents > 0
    ? (cents % 100 ? currencyCents : currencyWhole).format(cents / 100)
    : 'Precio no informado';
  const fold = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const textNode = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  };
  // El precio de lista publicado por Vea llega con valores inconsistentes en la muestra.
  const hasDiscount = p => p.origen !== 'Vea' && (p.origen !== 'Sidecompras' || Number(p.descuento) > 0) && Number(p.precio_centavos) > 0 && Number(p.precio_vigente_centavos) > 0 && Number(p.precio_vigente_centavos) < Number(p.precio_centavos);
  const discountAmount = p => Number(p.descuento) || Math.round((1 - Number(p.precio_vigente_centavos) / Number(p.precio_centavos)) * 100);
  function comparisonFor(p) {
    const cached = comparisonCache.get(p);
    if (cached && cached.until > Date.now()) { filteredUntil = Math.min(filteredUntil, cached.until); return cached.value; }
    const value = calculateComparison(p);
    // Refresh at least every 30 seconds and never keep an expired reference.
    let until = Date.now() + 30000;
    if (value) {
      for (const date of [value.observado, ...value.referencias.map(ref => ref.observado)]) until = Math.min(until, Date.parse(date) + 48 * 60 * 60 * 1000);
    }
    comparisonCache.set(p, {value, until});
    filteredUntil = Math.min(filteredUntil, until);
    return value;
  }
  function calculateComparison(p) {
    const comparison = state.comparisons[p.codigo];
    if (!comparison || !Number.isSafeInteger(p.precio_vigente_centavos) || p.precio_vigente_centavos <= 0 || comparison.precio_centavos !== p.precio_vigente_centavos) return null;
    const observed = Date.parse(comparison.observado);
    if (!Number.isFinite(observed) || Date.now() - observed < 0 || Date.now() - observed > 48 * 60 * 60 * 1000) return null;
    const references = Array.isArray(comparison.referencias) ? comparison.referencias : [{tienda:comparison.referencia_tienda, precio_centavos:comparison.referencia_centavos, url:comparison.referencia_url, observado:comparison.observado}];
    if (!references.length) return null;
    const stores = new Set();
    for (const reference of references) {
      if (!reference || typeof reference.tienda !== 'string' || !reference.tienda.trim() || !Number.isSafeInteger(reference.precio_centavos) || reference.precio_centavos <= 0) return null;
      const referenceAge = Date.now() - Date.parse(reference.observado);
      if (!Number.isFinite(referenceAge) || referenceAge < 0 || referenceAge > 48 * 60 * 60 * 1000) return null;
      try { if (new URL(reference.url).protocol !== 'https:') return null; } catch { return null; }
      const storeKey = fold(reference.tienda.trim());
      if (stores.has(storeKey)) return null;
      stores.add(storeKey);
      if (comparison.tipo === 'ean' && !referenceIndex.has(referenceKey(comparison.ean, reference.url, reference.tienda, reference.precio_centavos))) return null;
    }
    const average = Math.round(references.reduce((sum, reference) => sum + reference.precio_centavos, 0) / references.length);
    const saving = (1 - p.precio_vigente_centavos / average) * 100;
    if (!Number.isFinite(saving) || saving <= 0) return null;
    return {...comparison, referencias:references, referencia_centavos:average, ahorro_porcentaje:saving};
  }
  function safePhoto(value) {
    try {
      const url = new URL(value, 'https://sidecompras.com.ar/');
      const host = url.hostname.toLowerCase();
      const marketImages = ['www.mgmstore.com.ar', '6weoa5xmoylnh9pt.public.blob.vercel-storage.com', 'images.fravega.com', 'selexhogar.com.ar', 'riiing.com.ar', 'static.hendel.com', 'http2.mlstatic.com'];
      const allowed = (host === 'sidecompras.com.ar' && url.pathname.startsWith('/fotos/')) || host === 'vtexassets.com' || host.endsWith('.vtexassets.com') || host === 'vteximg.com.br' || host.endsWith('.vteximg.com.br') || (host === 'acdn-us.mitiendanube.com' && url.pathname.startsWith('/stores/')) || marketImages.includes(host);
      return url.protocol === 'https:' && allowed ? url.href : '';
    } catch { return ''; }
  }
  function productUrl(p) {
    if (!p.origen || p.origen === 'Sidecompras') return `https://sidecompras.com.ar/#/producto/${encodeURIComponent(p.codigo)}`;
    try { const url = new URL(p.url); return url.protocol === 'https:' ? url.href : ''; } catch { return ''; }
  }
  function card(p) {
    const article = textNode('article', 'card', '');
    const picture = textNode('div', 'card-image', '');
    const imageUrl = safePhoto(p.foto);
    if (hasDiscount(p)) picture.append(textNode('span', 'badge', `${number.format(discountAmount(p))}% OFF`));
    if (imageUrl) {
      const image = document.createElement('img');
      image.src = imageUrl;
      image.alt = '';
      image.loading = 'lazy';
      image.decoding = 'async';
      image.referrerPolicy = 'no-referrer';
      image.addEventListener('error', () => image.replaceWith(textNode('span', 'no-image', '✳')), {once:true});
      picture.append(image);
    } else picture.append(textNode('span', 'no-image', '✳'));
    const body = textNode('div', 'card-body', '');
    body.append(textNode('div', 'card-category', `${p.origen || 'Sidecompras'} · ${p.rubro || 'Otros'}`));
    body.append(textNode('h3', '', p.titulo || 'Producto sin título'));
    body.append(textNode('div', 'merchant', [p.comercio, p.localidad].filter(Boolean).join(' · ') || 'Sidecompras'));
    const prices = textNode('div', 'price-row', '');
    prices.append(textNode('strong', 'price', money(p.precio_vigente_centavos)));
    if (hasDiscount(p)) prices.append(textNode('span', 'old-price', money(p.precio_centavos)));
    body.append(prices);
    body.append(textNode('div', 'price-condition', p.reintegro ? 'Bonificación sujeta a condiciones' : 'Precio publicado'));
    const comparison = comparisonFor(p);
    if (comparison) {
      const deal = textNode('div', 'deal-evidence', '');
      const count = comparison.referencias.length;
      const saving = percentFormat.format(comparison.ahorro_porcentaje);
      deal.append(textNode('strong', '', `${comparison.ahorro_porcentaje >= 40 ? 'Precio muy bajo · ' : ''}${saving}% menos ${count > 1 ? 'que el promedio' : `que ${comparison.referencias[0].tienda}`}`));
      deal.append(textNode('span', 'reference-average', count > 1 ? `Promedio de ${count} tiendas: ${money(comparison.referencia_centavos)}` : `Precio de referencia: ${money(comparison.referencia_centavos)}`));
      const details = textNode('details', 'reference-list', '');
      details.append(textNode('summary', '', `Ver ${count === 1 ? 'referencia' : `${count} referencias`}`));
      for (const reference of comparison.referencias) {
        const ref = textNode('a', '', `${reference.tienda}: ${money(reference.precio_centavos)} ↗`);
        ref.href = reference.url; ref.target = '_blank'; ref.rel = 'noopener noreferrer';
        details.append(ref);
      }
      const observed = dateFormat.format(new Date(comparison.observado));
      deal.append(details, textNode('span', '', `Lectura más antigua: ${observed} hs`));
      body.append(deal);
    }
    if (installmentPromoActive && p.origen === 'Sidecompras') {
      const currentCents = p.precio_vigente_centavos;
      const listedCents = p.precio_centavos;
      const otherBenefit = p.reintegro || Number(p.descuento) > 0 || (Number.isSafeInteger(listedCents) && Number.isSafeInteger(currentCents) && listedCents > currentCents);
      const base = otherBenefit ? listedCents : currentCents;
      const validBase = Number.isSafeInteger(base) && base > 0;
      const installment = textNode('a', 'installment-card', '');
      installment.append(textNode('span', '', validBase ? `24 cuotas de ${money(Math.round(base / 24))} aprox. · Black o Blanca` : '24 cuotas sin interés · Black o Blanca'));
      installment.append(document.createElement('br'));
      installment.append(textNode('span', '', validBase ? `18 cuotas de ${money(Math.round(base / 18))} aprox. · Platinum, Black o Blanca` : '18 cuotas sin interés · Platinum, Black o Blanca'));
      if (otherBenefit) {
        installment.append(document.createElement('br'));
        installment.append(textNode('span', '', validBase ? 'Estimado sobre precio sin descuento · confirmar condiciones' : 'Monto a confirmar en Sidecompras'));
      }
      installment.href = '#installmentPromo';
      installment.title = 'Ver condiciones de la promoción Sidecompras';
      body.append(installment);
    }
    const promotionAge = Date.now() - Date.parse(p.observado_tienda);
    if (p.origen !== 'Sidecompras' && Number.isFinite(promotionAge) && promotionAge >= 0 && promotionAge <= 48 * 60 * 60 * 1000 && Array.isArray(p.promociones)) {
      const promotions = p.promociones.filter(promo => {
        if (!promo || typeof promo.medio !== 'string') return false;
        if (promo.tipo === 'cuotas') return promo.sin_interes === true && Number.isInteger(promo.cantidad_cuotas) && promo.cantidad_cuotas > 1 && Number.isSafeInteger(promo.monto_cuota_centavos) && promo.monto_cuota_centavos > 0 && promo.total_centavos === p.precio_vigente_centavos;
        return promo.tipo === 'transferencia' && Number.isSafeInteger(promo.precio_centavos) && promo.precio_centavos > 0 && promo.precio_centavos < p.precio_vigente_centavos;
      }).slice(0, 2);
      if (promotions.length) {
        const box = textNode('div', 'store-promotions', '');
        for (const promo of promotions) {
          const description = promo.tipo === 'cuotas'
            ? `${promo.cantidad_cuotas} cuotas sin interés de ${money(promo.monto_cuota_centavos)} · ${promo.medio}`
            : `${money(promo.precio_centavos)} por transferencia`;
          box.append(textNode('strong', '', description));
        }
        box.append(textNode('span', '', promotions.some(promo => promo.tipo === 'transferencia') ? 'Precio sin envío; sujeto a condiciones y confirmación al comprar.' : 'Sujeto a condiciones de la tienda y confirmación al comprar.'));
        body.append(box);
      }
    }
    const link = document.createElement('a');
    link.className = 'card-link';
    const origin = p.origen || 'Sidecompras';
    const href = productUrl(p);
    if (!href) { article.append(picture, body); return article; }
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', `Ver ${p.titulo || 'producto'} en ${origin} (abre una nueva pestaña)`);
    link.append(document.createTextNode(`Ver en ${origin}`), textNode('span', '', '↗'));
    body.append(link);
    article.append(picture, body);
    return article;
  }
  function populateSelect(select, key) {
    const selected = select.value;
    while (select.options.length > 1) select.remove(1);
    const values = [...new Set(state.products.map(p => p[key]).filter(v => typeof v === 'string' && v.trim()))].sort((a,b) => a.localeCompare(b,'es'));
    for (const value of values) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
    select.value = selected;
  }
  function render() {
    let filtered = filteredCache;
    if (!filtered || Date.now() >= filteredUntil) {
      filteredUntil = Date.now() + 30000;
      const query = fold(els.search.value.trim());
      const words = query ? query.split(/\s+/) : [];
      filtered = state.products.filter(p => {
        return (!words.length || words.every(word => searchText(p).includes(word)))
          && (!els.origin.value || els.origin.value === (p.origen || 'Sidecompras'))
          && (!els.category.value || p.rubro === els.category.value)
          && (!els.merchant.value || p.comercio === els.merchant.value)
          && (state.filter !== 'discount' || hasDiscount(p))
          && (state.filter !== 'deal' || comparisonFor(p))
          && (state.filter !== 'new' || p.nuevo_tienda === true);
      });
      const sort = els.sort.value;
      if (sort === 'low' || sort === 'high') filtered.sort((a,b) => {
        const x = Number(a.precio_vigente_centavos) || 0, y = Number(b.precio_vigente_centavos) || 0;
        return !x ? 1 : !y ? -1 : sort === 'low' ? x - y : y - x;
      });
      if (sort === 'discount') filtered.sort((a,b) => (hasDiscount(b) ? discountAmount(b) : 0) - (hasDiscount(a) ? discountAmount(a) : 0));
      if (sort === 'best') filtered.sort((a,b) => (comparisonFor(b)?.ahorro_porcentaje || 0) - (comparisonFor(a)?.ahorro_porcentaje || 0));
      if (sort === 'az') filtered.sort((a,b) => String(a.titulo || '').localeCompare(String(b.titulo || ''),'es'));
      filteredCache = filtered;
    }
    const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    state.page = Math.min(state.page, pages);
    els.products.replaceChildren(...filtered.slice((state.page - 1) * PAGE_SIZE, state.page * PAGE_SIZE).map(card));
    els.resultCount.textContent = `${number.format(filtered.length)} ${filtered.length === 1 ? 'producto' : 'productos'}`;
    els.status.textContent = filtered.length ? '' : state.loadingOptional && state.filter === 'deal' ? 'Cargando comparaciones de precios…' : 'No encontramos productos con esos filtros. Probá con otra búsqueda.';
    els.pagination.replaceChildren();
    if (pages > 1) {
      const prev = textNode('button', '', '← Anterior'); prev.type = 'button'; prev.disabled = state.page === 1;
      const next = textNode('button', '', 'Siguiente →'); next.type = 'button'; next.disabled = state.page === pages;
      const label = textNode('span', '', `Página ${number.format(state.page)} de ${number.format(pages)}`);
      prev.addEventListener('click', () => changePage(-1));
      next.addEventListener('click', () => changePage(1));
      els.pagination.append(prev,label,next);
      if (pages > 2) {
        const pageInput = document.createElement('input');
        pageInput.type = 'number'; pageInput.required = true; pageInput.min = '1'; pageInput.max = String(pages); pageInput.value = String(state.page);
        pageInput.setAttribute('aria-label', `Ir a la página, de 1 a ${number.format(pages)}`);
        const go = textNode('button', '', 'Ir'); go.type = 'button';
        const goToPage = () => {
          const page = Number(pageInput.value);
          if (!Number.isInteger(page) || page < 1 || page > pages) { pageInput.reportValidity(); return; }
          state.page = page; render(); els.products.scrollIntoView({behavior:'smooth'});
        };
        go.addEventListener('click', goToPage);
        pageInput.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); goToPage(); } });
        els.pagination.append(pageInput, go);
      }
    }
  }
  function changePage(diff) { state.page += diff; render(); els.products.scrollIntoView({behavior:'smooth'}); }
  const searchCache = new WeakMap();
  function searchText(p) {
    if (!searchCache.has(p)) searchCache.set(p, fold([p.titulo,p.rubro,p.comercio,p.localidad,p.codigo].join(' ')));
    return searchCache.get(p);
  }
  function refreshFilters() { state.page = 1; filteredCache = null; render(); }
  let searchTimer;
  els.search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(refreshFilters, 120); });
  for (const name of ['origin','category','merchant','sort']) els[name].addEventListener('change', refreshFilters);
  document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll('.tab').forEach(tab => {const active = tab === button; tab.classList.toggle('selected',active); tab.setAttribute('aria-pressed',String(active));});
    refreshFilters();
  }));
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) {e.preventDefault(); els.search.focus();}
  });
  async function load() {
    // Start every request at once. Publish the main catalogue as soon as it is
    // ready; optional sources update the results independently as they arrive.
    const getJson = async url => {
      const response = await fetch(url, {cache:'no-cache'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    };
    const settle = promise => promise.then(value => ({value}), error => ({error}));
    const requests = [SOURCE, OTHER_SOURCE, MARKET_SOURCE, ...COMPARISON_SOURCES].map(url => settle(getJson(url)));
    try {
      const main = await requests[0];
      if (main.error) throw main.error;
      const data = main.value;
      if (!Array.isArray(data.productos) || data.total !== data.productos.length || !data.productos.every(p => p && typeof p.codigo === 'string' && typeof p.titulo === 'string')) throw new Error('Catálogo incompleto');
      state.products = data.productos.map(p => ({...p, origen: 'Sidecompras'}));
      const date = new Date(data.actualizado);
      if (Number.isNaN(date.getTime())) {els.updatedMetric.textContent = 'Sin fecha'; els.updatedDetail.textContent = 'Revisá la tienda';}
      else {els.updatedMetric.textContent = dateFormat.format(date); els.updatedDetail.textContent = 'Hora argentina';}
      const coverage = {
        main: `Sidecompras: ${number.format(data.total)} productos del catálogo.`,
        shops: ['Cargando otras tiendas…'],
        market: 'Cargando ofertas de SoloPrecio…',
        comparisons: '',
      };
      const directNames = new Set(['Sidecompras']);
      // Keep the same priority regardless of which parallel request finishes first.
      const comparisonsBySource = [{}, {}, {}];
      let remaining = requests.length - 1;
      function updateView() {
        state.comparisons = Object.assign({}, ...comparisonsBySource);
        invalidateData();
        $('dealCount').textContent = number.format(state.products.filter(comparisonFor).length);
        els.totalMetric.textContent = number.format(state.products.length);
        els.discountMetric.textContent = number.format(state.products.filter(hasDiscount).length);
        const pending = ['Coto','XTR','FullH4rd','Compra Gamer','Mercado Libre'].filter(name => !directNames.has(name));
        const notes = [coverage.main, ...coverage.shops, coverage.market];
        if (pending.length) notes.push(`${pending.join(', ')}: sin catálogo directo disponible por ahora; pueden existir ofertas a través de SoloPrecio.`);
        notes.push('Vea: precios tachados y descuentos porcentuales ocultos por inconsistencias en la fuente.');
        if (coverage.comparisons) notes.push(coverage.comparisons);
        els.sourceCoverage.textContent = notes.join('  ');
        populateSelect(els.origin, 'origen'); populateSelect(els.category, 'rubro'); populateSelect(els.merchant, 'comercio');
        render();
      }
      updateView();
      await Promise.all(requests.slice(1).map(async (request, index) => {
        const result = await request;
        try {
          if (result.error) throw result.error;
          const value = result.value;
          if (index === 0) {
            if (!Array.isArray(value.tiendas)) throw new Error('Formato inválido');
            coverage.shops = [];
            for (const shop of value.tiendas) {
              if (typeof shop.nombre !== 'string' || !Array.isArray(shop.productos)) continue;
              const items = shop.productos.filter(p => p && typeof p.codigo === 'string' && typeof p.titulo === 'string').map(p => ({...p, origen:shop.nombre, observado_tienda:shop.actualizado}));
              state.products.push(...items);
              directNames.add(shop.nombre);
              const c = shop.cobertura || {};
              let message = `${shop.nombre}: ${number.format(items.length)} productos`;
              if (c.completa === true) message += ' (catálogo completo)';
              else message += ` (muestra parcial${Number.isInteger(c.total_publicado) ? ` de ${number.format(c.total_publicado)} publicados` : ''})`;
              if (shop.error) message += ' · última lectura con error';
              if (shop.actualizado) {
                const checked = new Date(shop.actualizado);
                if (!Number.isNaN(checked.getTime())) message += ` · ${dateFormat.format(checked)} hs`;
              }
              coverage.shops.push(message + '.');
            }
          } else if (index === 1) {
            if (value.version !== 1 || !Array.isArray(value.productos) || !value.comparaciones || typeof value.comparaciones !== 'object') throw new Error('Formato inválido');
            const items = value.productos.filter(p => p && typeof p.codigo === 'string' && typeof p.titulo === 'string' && typeof p.origen === 'string');
            state.products.push(...items);
            comparisonsBySource[index - 1] = value.comparaciones;
            coverage.market = `SoloPrecio: ${number.format(items.length)} ofertas de celulares de tiendas externas; cobertura parcial.`;
          } else {
            if (value.version !== 1 || !value.comparaciones || typeof value.comparaciones !== 'object' || Array.isArray(value.comparaciones)) throw new Error('Formato inválido');
            comparisonsBySource[index - 1] = value.comparaciones;
          }
        } catch (error) {
          console.warn('Fuente adicional no disponible:', error);
          if (index === 0) coverage.shops = ['Vea y Más Online: datos adicionales no disponibles en este momento.'];
          else if (index === 1) coverage.market = 'SoloPrecio: ofertas adicionales no disponibles en este momento.';
          else coverage.comparisons = 'Algunas comparaciones de precios no están disponibles en este momento.';
        }
        remaining--;
        state.loadingOptional = remaining > 0;
        updateView();
      }));
    } catch (error) {
      console.error('No se pudo cargar el catálogo:', error);
      els.status.textContent = 'No pudimos cargar el catálogo en este momento. Probá recargar la página.';
      els.sourceCoverage.textContent = 'No se pudieron actualizar las fuentes. Intentá nuevamente.';
      els.resultCount.textContent = 'Catálogo no disponible';
      els.updatedMetric.textContent = 'Sin conexión';
      els.updatedDetail.textContent = 'Intentá nuevamente';
    }
  }
  load();
})();
