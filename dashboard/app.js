(() => {
  'use strict';

  const SOURCE = 'https://raw.githubusercontent.com/gabyboan/sidescrapping/main/catalogo.json';
  const OTHER_SOURCE = 'https://raw.githubusercontent.com/gabyboan/sidescrapping/main/supermercados.json';
  const COMPARISON_SOURCES = ['comparaciones.json', 'comparaciones_side.json'].map(name => `https://raw.githubusercontent.com/gabyboan/sidescrapping/main/${name}`);
  const PAGE_SIZE = 24;
  // Plan 7: expire at midnight in Argentina after the published end date.
  const installmentPromoActive = Date.now() >= Date.parse('2026-01-01T03:00:00Z') && Date.now() < Date.parse('2027-01-01T03:00:00Z');
  const $ = id => document.getElementById(id);
  $('installmentPromo').hidden = !installmentPromoActive;
  const els = Object.fromEntries(['search','origin','category','merchant','sort','products','status','pagination','resultCount','totalMetric','discountMetric','updatedMetric','updatedDetail','sourceCoverage'].map(id => [id, $(id)]));
  const state = {products: [], comparisons: {}, filter: 'all', page: 1};
  const number = new Intl.NumberFormat('es-AR');
  const money = cents => typeof cents === 'number' && Number.isFinite(cents) && cents > 0
    ? new Intl.NumberFormat('es-AR', {style:'currency', currency:'ARS', minimumFractionDigits: cents % 100 ? 2 : 0, maximumFractionDigits:2}).format(cents / 100)
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
    const comparison = state.comparisons[p.codigo];
    if (!comparison || comparison.precio_centavos !== p.precio_vigente_centavos || !Number.isSafeInteger(comparison.referencia_centavos) || comparison.referencia_centavos <= 0 || !Number.isFinite(comparison.ahorro_porcentaje) || comparison.ahorro_porcentaje < 20) return null;
    const observed = Date.parse(comparison.observado);
    if (!Number.isFinite(observed) || Date.now() - observed < 0 || Date.now() - observed > 48 * 60 * 60 * 1000) return null;
    try { if (new URL(comparison.referencia_url).protocol !== 'https:') return null; } catch { return null; }
    if (comparison.tipo === 'ean' && !state.products.some(reference => reference.ean === comparison.ean && reference.url === comparison.referencia_url && reference.origen === comparison.referencia_tienda && reference.disponible === true && reference.precio_vigente_centavos === comparison.referencia_centavos)) return null;
    return comparison;
  }
  function safePhoto(value) {
    try {
      const url = new URL(value, 'https://sidecompras.com.ar/');
      const host = url.hostname.toLowerCase();
      const allowed = (host === 'sidecompras.com.ar' && url.pathname.startsWith('/fotos/')) || host === 'vtexassets.com' || host.endsWith('.vtexassets.com') || host === 'vteximg.com.br' || host.endsWith('.vteximg.com.br') || (host === 'acdn-us.mitiendanube.com' && url.pathname.startsWith('/stores/'));
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
      deal.append(textNode('strong', '', `${Math.floor(comparison.ahorro_porcentaje)}% menos que ${comparison.referencia_tienda}`));
      const ref = textNode('a', '', `Referencia: ${money(comparison.referencia_centavos)} ↗`);
      ref.href = comparison.referencia_url;
      ref.target = '_blank'; ref.rel = 'noopener noreferrer';
      const observed = new Intl.DateTimeFormat('es-AR', {timeZone:'America/Argentina/Buenos_Aires', day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}).format(new Date(comparison.observado));
      deal.append(ref, textNode('span', '', `Consultado: ${observed} hs`));
      body.append(deal);
    }
    if (installmentPromoActive && p.origen === 'Sidecompras') {
      const currentCents = p.precio_vigente_centavos;
      const listedCents = p.precio_centavos;
      let installmentText = '24 cuotas sin interés · Blanca o Black';
      const otherBenefit = p.reintegro || Number(p.descuento) > 0 || (Number.isSafeInteger(listedCents) && Number.isSafeInteger(currentCents) && listedCents > currentCents);
      if (otherBenefit) {
        installmentText = Number.isSafeInteger(listedCents) && listedCents > 0
          ? `24 cuotas de ${money(Math.round(listedCents / 24))} aprox. sobre precio sin descuento · confirmar condiciones`
          : '24 cuotas sin interés · monto a confirmar en Sidecompras';
      } else if (Number.isSafeInteger(currentCents) && currentCents > 0) {
        installmentText = `24 cuotas de ${money(Math.round(currentCents / 24))} aprox. sin interés · Blanca o Black`;
      }
      const installment = textNode('a', 'installment-card', installmentText);
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
    const values = [...new Set(state.products.map(p => p[key]).filter(v => typeof v === 'string' && v.trim()))].sort((a,b) => a.localeCompare(b,'es'));
    for (const value of values) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
  }
  function render() {
    const query = fold(els.search.value.trim());
    const filtered = state.products.filter(p => {
      const haystack = fold([p.titulo,p.rubro,p.comercio,p.localidad,p.codigo].join(' '));
      return (!query || query.split(/\s+/).every(word => haystack.includes(word)))
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
    if (sort === 'az') filtered.sort((a,b) => String(a.titulo || '').localeCompare(String(b.titulo || ''),'es'));
    const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    state.page = Math.min(state.page, pages);
    els.products.replaceChildren(...filtered.slice((state.page - 1) * PAGE_SIZE, state.page * PAGE_SIZE).map(card));
    els.resultCount.textContent = `${number.format(filtered.length)} ${filtered.length === 1 ? 'producto' : 'productos'}`;
    els.status.textContent = filtered.length ? '' : 'No encontramos productos con esos filtros. Probá con otra búsqueda.';
    els.pagination.replaceChildren();
    if (pages > 1) {
      const prev = textNode('button', '', '← Anterior'); prev.type = 'button'; prev.disabled = state.page === 1;
      const next = textNode('button', '', 'Siguiente →'); next.type = 'button'; next.disabled = state.page === pages;
      const label = textNode('span', '', `Página ${number.format(state.page)} de ${number.format(pages)}`);
      prev.addEventListener('click', () => changePage(-1));
      next.addEventListener('click', () => changePage(1));
      els.pagination.append(prev,label,next);
    }
  }
  function changePage(diff) { state.page += diff; render(); $('catalogo').scrollIntoView({behavior:'smooth'}); }
  function refreshFilters() { state.page = 1; render(); }
  for (const name of ['search','origin','category','merchant','sort']) els[name].addEventListener(name === 'search' ? 'input' : 'change', refreshFilters);
  document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll('.tab').forEach(tab => {const active = tab === button; tab.classList.toggle('selected',active); tab.setAttribute('aria-pressed',String(active));});
    refreshFilters();
  }));
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) {e.preventDefault(); els.search.focus();}
  });
  async function load() {
    try {
      const response = await fetch(`${SOURCE}?timestamp=${Date.now()}`, {cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.productos) || data.total !== data.productos.length || !data.productos.every(p => p && typeof p.codigo === 'string' && typeof p.titulo === 'string')) throw new Error('Catálogo incompleto');
      state.products = data.productos.map(p => ({...p, origen: 'Sidecompras'}));
      const date = new Date(data.actualizado);
      if (Number.isNaN(date.getTime())) {els.updatedMetric.textContent = 'Sin fecha'; els.updatedDetail.textContent = 'Revisá la tienda';}
      else {
        els.updatedMetric.textContent = new Intl.DateTimeFormat('es-AR',{timeZone:'America/Argentina/Buenos_Aires',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(date);
        els.updatedDetail.textContent = 'Hora argentina';
      }
      const coverage = [`Sidecompras: ${number.format(data.total)} productos del catálogo.`];
      try {
        const extraResponse = await fetch(`${OTHER_SOURCE}?timestamp=${Date.now()}`, {cache:'no-store'});
        if (!extraResponse.ok) throw new Error(`HTTP ${extraResponse.status}`);
        const extra = await extraResponse.json();
        if (!Array.isArray(extra.tiendas)) throw new Error('Formato inválido');
        for (const shop of extra.tiendas) {
          if (typeof shop.nombre !== 'string' || !Array.isArray(shop.productos)) continue;
          const items = shop.productos.filter(p => p && typeof p.codigo === 'string' && typeof p.titulo === 'string').map(p => ({...p, origen:shop.nombre, observado_tienda:shop.actualizado}));
          state.products.push(...items);
          const c = shop.cobertura || {};
          let message = `${shop.nombre}: ${number.format(items.length)} productos`;
          if (c.completa === true) message += ' (catálogo completo)';
          else message += ` (muestra parcial${Number.isInteger(c.total_publicado) ? ` de ${number.format(c.total_publicado)} publicados` : ''})`;
          if (shop.error) message += ' · última lectura con error';
          if (shop.actualizado) {
            const checked = new Date(shop.actualizado);
            if (!Number.isNaN(checked.getTime())) message += ` · ${new Intl.DateTimeFormat('es-AR',{timeZone:'America/Argentina/Buenos_Aires',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(checked)} hs`;
          }
          coverage.push(message + '.');
        }
      } catch (error) {
        console.warn('Fuentes adicionales no disponibles:', error);
        coverage.push('Vea y Más Online: datos adicionales no disponibles en este momento.');
      }
      const names = new Set(state.products.map(p => p.origen));
      const pending = ['Coto','XTR','FullH4rd','Compra Gamer','Mercado Libre'].filter(name => !names.has(name));
      if (pending.length) coverage.push(`${pending.join(', ')}: sin catálogo disponible por ahora.`);
      coverage.push('Vea: precios tachados y descuentos porcentuales ocultos por inconsistencias en la fuente.');
      const comparisons = await Promise.allSettled(COMPARISON_SOURCES.map(async url => {
        const response = await fetch(`${url}?timestamp=${Date.now()}`, {cache:'no-store'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (data.version !== 1 || !data.comparaciones || typeof data.comparaciones !== 'object' || Array.isArray(data.comparaciones)) throw new Error('Formato inválido');
        return data.comparaciones;
      }));
      for (const result of comparisons) if (result.status === 'fulfilled') Object.assign(state.comparisons, result.value);
      const dealCount = state.products.filter(comparisonFor).length;
      $('dealCount').textContent = number.format(dealCount);
      if (comparisons.some(result => result.status === 'rejected')) coverage.push('Algunas comparaciones de precios no están disponibles en este momento.');
      els.sourceCoverage.textContent = coverage.join('  ');
      els.totalMetric.textContent = number.format(state.products.length);
      els.discountMetric.textContent = number.format(state.products.filter(hasDiscount).length);
      populateSelect(els.origin, 'origen'); populateSelect(els.category, 'rubro'); populateSelect(els.merchant, 'comercio');
      render();
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
