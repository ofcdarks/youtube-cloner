/* ── Auth Token ───────────────────────────────────────── */

(function() {
    // Priority: URL param > window inject > localStorage
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get('_token');
    if (urlToken) {
        localStorage.setItem('session_token', urlToken);
        window.history.replaceState({}, '', window.location.pathname);
    } else if (window.__SESSION_TOKEN) {
        // Always update localStorage with current server session
        localStorage.setItem('session_token', window.__SESSION_TOKEN);
    }
})();

function getToken() {
    // Server-injected token is always freshest
    return window.__SESSION_TOKEN || localStorage.getItem('session_token') || '';
}

/* ── Reload preserving project ───────────────────────── */

function reloadWithProject() {
    const pid = window.__CURRENT_PROJECT_ID;
    if (pid) {
        window.location.href = '/?project=' + encodeURIComponent(pid);
    } else {
        window.location.href = '/';
    }
}

/* ── API Helper (sends token via header) ─────────────── */

function api(url, options = {}) {
    options.credentials = 'include';
    if (!options.headers) options.headers = {};
    const token = getToken();
    if (token) {
        options.headers['X-Session'] = token;
    }
    // Include CSRF token for state-changing requests
    const csrfToken = window.CSRF_TOKEN || (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    if (csrfToken) {
        options.headers['X-CSRF-Token'] = csrfToken;
    }
    return fetch(url, options).then(r => {
        if (r.status === 401) { window.location.href = '/login'; throw new Error('unauthorized'); }
        if (r.status === 403) {
            return r.clone().json().then(d => {
                if (d.error && d.error.indexOf('CSRF') >= 0) {
                    showToast('Sessao expirada. Recarregando...', 'warning');
                    setTimeout(() => window.location.reload(), 1500);
                }
                return r;
            }).catch(() => r);
        }
        return r;
    });
}

function apiPost(url, data) {
    return api(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
    });
}

/* ── Toast / Notification System ─────────────────────── */

function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container') || createToastContainer();
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;

    const icons = {success: '&#10003;', error: '&#10007;', info: '&#9432;', warning: '&#9888;', loading: '&#9881;'};
    toast.innerHTML = '<span class="toast-icon">' + (icons[type] || icons.info) + '</span><span class="toast-msg">' + message + '</span>';

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));

    if (type !== 'loading') {
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
    return toast;
}

function createToastContainer() {
    const c = document.createElement('div');
    c.id = 'toast-container';
    document.body.appendChild(c);
    return c;
}

function removeToast(toast) {
    if (toast) {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }
}


/* ── Confirm Dialog ──────────────────────────────────── */

function showConfirm(title, message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
        <div class="confirm-box">
            <div class="confirm-icon">&#9888;</div>
            <h3 class="confirm-title">${title}</h3>
            <p class="confirm-msg">${message}</p>
            <div class="confirm-actions">
                <button class="confirm-btn cancel" onclick="this.closest('.confirm-overlay').remove()">Cancelar</button>
                <button class="confirm-btn ok" id="confirm-ok">Confirmar</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('active'));

    overlay.querySelector('#confirm-ok').addEventListener('click', () => {
        onConfirm();
        overlay.remove();
    });
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}


/* ── Input Dialog ────────────────────────────────────── */

function showInput(title, fields, onSubmit) {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';

    let fieldsHtml = '';
    fields.forEach(f => {
        fieldsHtml += `<label class="input-label">${f.label}</label>
            <input class="input-field" type="${f.type || 'text'}" id="input-${f.name}" value="${f.default || ''}" placeholder="${f.placeholder || ''}">`;
    });

    overlay.innerHTML = `
        <div class="confirm-box">
            <h3 class="confirm-title">${title}</h3>
            ${fieldsHtml}
            <div class="confirm-actions">
                <button class="confirm-btn cancel" onclick="this.closest('.confirm-overlay').remove()">Cancelar</button>
                <button class="confirm-btn ok" id="input-submit">Gerar</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('active'));

    overlay.querySelector('#input-submit').addEventListener('click', () => {
        const values = {};
        fields.forEach(f => { values[f.name] = document.getElementById('input-' + f.name).value; });
        overlay.remove();
        onSubmit(values);
    });
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}


/* ── Niche Selection ──────────────────────────────────── */

function selectNiche(el, name) {
    // Toggle selection (max 2) — persists to DB
    const selected = document.querySelectorAll('.niche-selected');
    const isSelected = el.classList.contains('niche-selected');
    const newChosen = !isSelected;

    if (!isSelected && selected.length >= 2) {
        showToast('Maximo 2 nichos! Desmarque um primeiro.', 'warning', 3000);
        return;
    }

    const projectId = window.__CURRENT_PROJECT_ID || '';
    if (!projectId) {
        showToast('Projeto nao identificado', 'error');
        return;
    }

    apiPost('/api/admin/toggle-niche-chosen', {
        name: name,
        project_id: projectId,
        chosen: newChosen,
    }).then(r => r.json()).then(data => {
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }
        if (newChosen) {
            el.classList.add('niche-selected');
            const nameDiv = el.querySelector('.niche-name');
            if (nameDiv && !nameDiv.querySelector('.chosen-badge')) {
                nameDiv.insertAdjacentHTML('beforeend', ' <span class="chosen-badge">ESCOLHIDO</span>');
            }
            showToast('"' + name + '" selecionado!', 'success', 2000);
        } else {
            el.classList.remove('niche-selected');
            const badge = el.querySelector('.chosen-badge');
            if (badge) badge.remove();
            showToast('"' + name + '" desmarcado', 'info', 2000);
        }
    }).catch(() => showToast('Erro ao salvar nicho', 'error'));
}

/* ── File/Project Viewer Modal ───────────────────────── */

function loadFile(path) {
    api('/file?path=' + encodeURIComponent(path))
        .then(r => {
            if (!r.ok) { showToast('Sessao expirada. Faca login novamente.', 'error'); return Promise.reject(); }
            return r.text();
        })
        .then(text => {
            if (!text) return;
            const name = path.split('/').pop().replace('.md','').replace(/_/g,' ');
            document.getElementById('modal-title').textContent = name;
            document.getElementById('modal-body').textContent = text;
            document.getElementById('modal').classList.add('active');
        })
        .catch(() => {});
}

function copyFile(path) {
    api('/file?path=' + encodeURIComponent(path))
        .then(r => {
            if (!r.ok) { showToast('Sessao expirada. Faca login novamente.', 'error'); return Promise.reject(); }
            return r.text();
        })
        .then(text => {
            if (!text) return;
            navigator.clipboard.writeText(text).then(() => {
                showToast('Conteudo copiado!', 'success', 2000);
            }).catch(() => {
                showToast('Erro ao copiar', 'error');
            });
        })
        .catch(() => {});
}

function copyModalContent() {
    const body = document.getElementById('modal-body');
    if (!body || !body.textContent) { showToast('Nada para copiar', 'warning', 2000); return; }
    navigator.clipboard.writeText(body.textContent).then(() => {
        showToast('Conteudo copiado!', 'success', 2000);
    }).catch(() => {
        showToast('Erro ao copiar', 'error');
    });
}

function loadProject(id) {
    api('/project?id=' + id)
        .then(r => r.text())
        .then(text => {
            document.getElementById('modal-title').textContent = 'Projeto: ' + id;
            document.getElementById('modal-body').textContent = text;
            document.getElementById('modal').classList.add('active');
        });
}

function closeModal() {
    document.getElementById('modal').classList.remove('active');
}

document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('modal');
    if (modal) {
        modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
});


/* ── Toggle Used ─────────────────────────────────────── */

function toggleUsed(id) {
    apiPost('/api/toggle-used', {id: id})
    .then(r => r.json())
    .then(data => {
        if (data.error) { showToast(data.error, 'error'); return; }
        const row = document.getElementById('idea-' + id);
        if (data.used) {
            row.style.opacity = '0.4';
            row.style.textDecoration = 'line-through';
            row.querySelector('.idea-check').innerHTML = '&#9745;';
            showToast('Titulo marcado como usado', 'success', 2000);
        } else {
            row.style.opacity = '1';
            row.style.textDecoration = 'none';
            row.querySelector('.idea-check').innerHTML = '&#9744;';
            showToast('Titulo desmarcado', 'info', 2000);
        }
    })
    .catch(() => showToast('Erro ao atualizar', 'error'));
}


/* ── Idea Details ────────────────────────────────────── */

function showIdeaDetails(id) {
    api('/api/idea-details?id=' + id)
    .then(r => r.json())
    .then(data => {
        if (data.error) { showToast(data.error, 'error'); return; }
        let details = data.score_details || {};
        let text = 'TITULO: ' + data.title + '\n';
        text += 'Score: ' + (data.score || 0) + '/100 (' + (data.rating || '-') + ')\n';
        text += 'Prioridade: ' + (data.priority || '-') + '\n';
        text += 'Pilar: ' + (data.pillar || '-') + '\n\n';

        if (details.youtube) {
            text += '=== YOUTUBE ===\n';
            text += 'Score: ' + (details.youtube.score || 0) + '/100\n';
            text += 'Views medio: ' + (details.youtube.avg_views || 0).toLocaleString() + '\n';
            text += 'Views maximo: ' + (details.youtube.max_views || 0).toLocaleString() + '\n';
            text += 'Resultados similares: ' + (details.youtube.results_found || 0) + '\n';
            if (details.youtube.top_titles) {
                text += 'Top videos:\n';
                details.youtube.top_titles.forEach(t => text += '  - ' + t + '\n');
            }
            text += '\n';
        }

        if (details.regional_scores) {
            text += '=== POR REGIAO ===\n';
            Object.entries(details.regional_scores).forEach(([code, r]) => {
                let arrow = r.trend === 'subindo' ? '^' : r.trend === 'descendo' ? 'v' : '=';
                text += r.name + ': ' + r.trends_score + '/100 ' + arrow + ' (' + r.trend + ')\n';
                text += '  Interesse medio: ' + (r.avg_interest || 0) + '\n';
                text += '  Keywords: ' + (r.keywords || []).join(', ') + '\n';
            });
            text += '\n';
        }

        if (details.top_countries && Object.keys(details.top_countries).length > 0) {
            text += '=== TOP PAISES ===\n';
            Object.entries(details.top_countries).forEach(([c, v]) => {
                text += '  ' + c + ': ' + v + '\n';
            });
            text += '\n';
        }

        if (details.best_opportunity) {
            text += 'MELHOR OPORTUNIDADE: ' + details.best_opportunity + '\n';
        }

        document.getElementById('modal-title').textContent = 'Analise: ' + data.title;
        document.getElementById('modal-body').textContent = text;
        document.getElementById('modal').classList.add('active');
    });
}


/* ── Progress Modal ─────────────────────────────────── */

function showProgressModal(title) {
    // Remove existing if any
    closeProgressModal();
    const overlay = document.createElement('div');
    overlay.id = 'progress-modal';
    overlay.className = 'progress-modal-overlay';
    overlay.innerHTML = `
        <div class="progress-modal-box">
            <h3 class="progress-modal-title">${title}</h3>
            <div class="progress-modal-bar-bg">
                <div class="progress-modal-bar-fill" id="progress-bar-fill" style="width:0%"></div>
            </div>
            <div class="progress-modal-pct" id="progress-pct">0%</div>
            <div class="progress-modal-status" id="progress-status">Iniciando...</div>
        </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('active'));
}

function updateProgress(percent, status) {
    const bar = document.getElementById('progress-bar-fill');
    const pct = document.getElementById('progress-pct');
    const st = document.getElementById('progress-status');
    if (bar) bar.style.width = percent + '%';
    if (pct) pct.textContent = Math.round(percent) + '%';
    if (st && status) st.textContent = status;
}

function closeProgressModal() {
    const modal = document.getElementById('progress-modal');
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => modal.remove(), 300);
    }
}


/* ── Generate More Ideas ─────────────────────────────── */

function generateMoreIdeas() {
    const currentNiche = (window.__CURRENT_PROJECT_ID || '').replace(/_/g, ' ').replace(/^\d+\s*/, '');
    showInput('Gerar Novos Titulos', [
        {name: 'niche', label: 'Nicho', default: currentNiche || 'System Breakers', placeholder: 'Ex: Dark Deals, Heist Architects...'},
        {name: 'count', label: 'Quantidade', type: 'number', default: '10', placeholder: '10'},
    ], (values) => {
        const btn = document.getElementById('ideas-btn');
        btn.disabled = true;
        btn.textContent = 'Gerando...';

        showProgressModal('Gerando Titulos');
        updateProgress(20, 'Gerando ' + values.count + ' titulos para "' + values.niche + '"...');

        apiPost('/api/generate-ideas', {
            niche: values.niche,
            count: parseInt(values.count),
            project_id: window.__CURRENT_PROJECT_ID || '',
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                updateProgress(100, data.generated + ' titulos gerados com sucesso!');
                showToast(data.generated + ' titulos gerados com sucesso!', 'success');
                setTimeout(() => { closeProgressModal(); reloadWithProject(); }, 1500);
            } else {
                closeProgressModal();
                showToast('Erro: ' + (data.error || 'desconhecido'), 'error');
                btn.disabled = false;
                btn.textContent = '+ Gerar Titulos';
            }
        })
        .catch(e => {
            closeProgressModal();
            showToast('Erro: ' + e.message, 'error');
            btn.disabled = false;
            btn.textContent = '+ Gerar Titulos';
        });
    });
}

function regenerateFromNiches() {
    showConfirm(
        'Refazer Titulos pelos Nichos',
        'Isso vai <strong>APAGAR todos os titulos atuais</strong> e gerar 30 novos baseados nos nichos escolhidos (marcados como ESCOLHIDO).<br><br>O SOP original sera usado como referencia de tom e estilo.<br><br>Continuar?',
        function() {
            showProgressModal('Refazendo Titulos');
            updateProgress(10, 'Apagando titulos antigos...');

            apiPost('/api/admin/regenerate-titles', {
                project_id: window.__CURRENT_PROJECT_ID || '',
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok) {
                    updateProgress(100, data.generated + ' titulos gerados baseados em ' + data.niches_used + ' nicho(s)!');
                    showToast(data.generated + ' titulos gerados!', 'success');
                    setTimeout(function() { closeProgressModal(); reloadWithProject(); }, 2000);
                } else {
                    closeProgressModal();
                    showToast('Erro: ' + (data.error || ''), 'error');
                }
            })
            .catch(function(e) {
                closeProgressModal();
                showToast('Erro: ' + e.message, 'error');
            });
        }
    );
}

function changeProjectLanguage(lang) {
    if (!lang) return;
    fetch('/api/admin/set-project-language', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': window.CSRF_TOKEN || ''
        },
        body: JSON.stringify({
            project_id: window.__CURRENT_PROJECT_ID || '',
            language: lang
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            showToast('Idioma alterado para ' + lang, 'success', 2000);
        } else {
            showToast('Erro: ' + (data.error || ''), 'error');
        }
    })
    .catch(function(e) {
        showToast('Erro: ' + e.message, 'error');
    });
}

function regenerateNiches() {
    showConfirm(
        'Regenerar Nichos',
        'Isso vai <strong>APAGAR todos os nichos atuais</strong> e gerar 5 novos baseados no SOP do projeto.<br><br>As descricoes serao em PT-BR e os melhores nichos terao selo RECOMENDADO.<br><br>Continuar?',
        function() {
            var btn = document.getElementById('regen-niches-btn');
            if (btn) { btn.disabled = true; btn.textContent = 'Gerando...'; }
            showProgressModal('Regenerando Nichos');
            updateProgress(30, 'Analisando SOP e gerando 5 nichos otimizados...');

            fetch('/api/admin/regenerate-niches', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': window.CSRF_TOKEN || ''
                },
                body: JSON.stringify({
                    project_id: window.__CURRENT_PROJECT_ID || '',
                })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok) {
                    updateProgress(100, data.generated + ' nichos gerados!');
                    showToast(data.generated + ' nichos gerados com sucesso!', 'success');
                    setTimeout(function() { closeProgressModal(); reloadWithProject(); }, 1500);
                } else {
                    closeProgressModal();
                    showToast('Erro: ' + (data.error || 'desconhecido'), 'error');
                }
                if (btn) { btn.disabled = false; btn.textContent = '\uD83D\uDD04 Regenerar Nichos'; }
            })
            .catch(function(e) {
                closeProgressModal();
                showToast('Erro: ' + e.message, 'error');
                if (btn) { btn.disabled = false; btn.textContent = '\uD83D\uDD04 Regenerar Nichos'; }
            });
        }
    );
}

/* ── Generate Script ─────────────────────────────────── */

function generateScript(id, title) {
    showConfirm('Gerar Roteiro', 'Gerar roteiro para:<br><br><strong>"' + title + '"</strong><br><br>Usa a API (laozhang.ai) e pode levar 1-2 minutos.', () => {
        const btn = document.querySelector('#idea-' + id + ' .gen-btn');
        if (btn) { btn.disabled = true; btn.textContent = '...'; }

        showProgressModal('Gerando Roteiro');
        updateProgress(10, 'Enviando para a API...');

        // Real elapsed timer instead of fake progress
        const startTime = Date.now();
        const scriptInterval = setInterval(() => {
            const elapsed = Math.round((Date.now() - startTime) / 1000);
            const pct = Math.min(85, 10 + elapsed);
            const msg = elapsed < 15 ? 'Analisando SOP do canal...'
                      : elapsed < 40 ? 'Escrevendo roteiro... (' + elapsed + 's)'
                      : elapsed < 70 ? 'Finalizando... (' + elapsed + 's)'
                      : 'Aguardando resposta da API... (' + elapsed + 's)';
            updateProgress(pct, msg);
        }, 1000);

        apiPost('/api/generate-script', {idea_id: id})
        .then(r => r.json())
        .then(data => {
            clearInterval(scriptInterval);
            if (data.ok) {
                updateProgress(100, 'Roteiro gerado! ' + data.script_words + ' palavras (' + data.duration_estimate + ')');
                setTimeout(function() {
                    closeProgressModal();
                    showScriptResultModal(data);
                }, 800);
            } else {
                closeProgressModal();
                showToast('Erro: ' + (data.error || 'desconhecido'), 'error', 6000);
                if (btn) { btn.disabled = false; btn.textContent = '\u270E'; }
            }
        })
        .catch(e => {
            clearInterval(scriptInterval);
            closeProgressModal();
            showToast('Erro: ' + e.message, 'error');
            if (btn) { btn.disabled = false; btn.textContent = '\u270E'; }
        });
    });
}


/* ── Script Result Modal (after generating a script) ─────── */

function showScriptResultModal(data) {
    var existing = document.getElementById('script-result-modal');
    if (existing) existing.remove();

    var modal = document.createElement('div');
    modal.id = 'script-result-modal';
    modal.className = 'modal-overlay active';
    modal.style.cssText = 'align-items:flex-start;padding:24px';

    var script = data.script || '';
    var narration = data.narration || '';
    var title = data.title || 'Roteiro';
    var words = data.words || 0;
    var nWords = data.narration_words || 0;
    var duration = data.duration_estimate || '';

    modal.innerHTML =
        '<div class="modal-content" style="max-width:980px;width:100%;max-height:92vh">' +
            '<div class="modal-header" style="border-bottom:1px solid #1f2937">' +
                '<div>' +
                    '<h3 style="margin:0">📝 Roteiro Gerado</h3>' +
                    '<div style="font-size:11px;color:#94a3b8;margin-top:4px">' + escapeHtmlSafe(title) + '</div>' +
                '</div>' +
                '<button class="modal-close" onclick="closeScriptResultModal()">&#10005;</button>' +
            '</div>' +
            '<div style="display:flex;gap:0;border-bottom:1px solid #1f2937;background:rgba(0,0,0,0.3)">' +
                '<button id="srm-tab-narration" class="srm-tab srm-tab-active" onclick="switchScriptTab(\'narration\')" style="flex:1;background:none;border:none;border-bottom:2px solid #FFD700;color:#fff;padding:14px;font-size:13px;font-weight:700;cursor:pointer">' +
                    '🎙️ Narração Limpa <span style="color:#FFD700">(pro Agente)</span> · ' + nWords.toLocaleString() + ' palavras' +
                '</button>' +
                '<button id="srm-tab-script" class="srm-tab" onclick="switchScriptTab(\'script\')" style="flex:1;background:none;border:none;border-bottom:2px solid transparent;color:#94a3b8;padding:14px;font-size:13px;font-weight:600;cursor:pointer">' +
                    '📜 Roteiro Completo · ' + words.toLocaleString() + ' palavras · ' + duration +
                '</button>' +
            '</div>' +
            '<div style="padding:14px 20px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center">' +
                '<button class="btn-primary" id="srm-copy-btn" onclick="copyScriptResult()" style="background:linear-gradient(135deg,#FFD700,#FFA500);color:#000;font-size:12px;padding:8px 16px">📋 Copiar pro Agente</button>' +
                '<button class="btn-primary" onclick="downloadScriptResult()" style="background:#1e293b;color:#cbd5e1;font-size:12px;padding:8px 16px">💾 Baixar .txt</button>' +
                '<span style="font-size:11px;color:#64748b;margin-left:auto">💾 Salvo em: <strong style="color:#94a3b8">' + escapeHtmlSafe(data.saved_to || 'Arquivos do Projeto') + '</strong></span>' +
            '</div>' +
            '<div style="padding:14px 20px 20px;flex:1;overflow-y:auto;min-height:0">' +
                '<textarea id="srm-content" readonly style="width:100%;min-height:55vh;background:#0a0a14;border:1px solid #1f2937;border-radius:8px;color:#e2e8f0;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;line-height:1.6;padding:14px;resize:vertical">' + escapeHtmlSafe(narration) + '</textarea>' +
            '</div>' +
        '</div>';

    document.body.appendChild(modal);

    // Store script + narration on the modal element so tab switching can swap them
    modal.dataset.script = script;
    modal.dataset.narration = narration;
    modal.dataset.title = title;
    modal.dataset.activeTab = 'narration';

    // Click outside closes
    modal.addEventListener('click', function(e) {
        if (e.target === modal) closeScriptResultModal();
    });
}

function escapeHtmlSafe(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function switchScriptTab(which) {
    var modal = document.getElementById('script-result-modal');
    if (!modal) return;
    var content = which === 'script' ? modal.dataset.script : modal.dataset.narration;
    document.getElementById('srm-content').value = content;
    document.getElementById('srm-tab-narration').style.borderBottomColor = which === 'narration' ? '#FFD700' : 'transparent';
    document.getElementById('srm-tab-narration').style.color = which === 'narration' ? '#fff' : '#94a3b8';
    document.getElementById('srm-tab-script').style.borderBottomColor = which === 'script' ? '#FFD700' : 'transparent';
    document.getElementById('srm-tab-script').style.color = which === 'script' ? '#fff' : '#94a3b8';
    modal.dataset.activeTab = which;
}

function copyScriptResult() {
    var ta = document.getElementById('srm-content');
    if (!ta) return;
    ta.select();
    ta.setSelectionRange(0, 999999);
    try {
        navigator.clipboard.writeText(ta.value).then(function() {
            var btn = document.getElementById('srm-copy-btn');
            if (btn) {
                var orig = btn.innerHTML;
                btn.innerHTML = '✓ Copiado!';
                setTimeout(function() { btn.innerHTML = orig; }, 1500);
            }
            showToast('Texto copiado pro clipboard', 'success', 2000);
        });
    } catch (e) {
        document.execCommand('copy');
        showToast('Texto copiado', 'success', 2000);
    }
}

function downloadScriptResult() {
    var modal = document.getElementById('script-result-modal');
    if (!modal) return;
    var which = modal.dataset.activeTab || 'narration';
    var content = which === 'script' ? modal.dataset.script : modal.dataset.narration;
    var title = modal.dataset.title || 'roteiro';
    var slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 60);
    var prefix = which === 'script' ? 'roteiro-' : 'narracao-';
    var blob = new Blob([content], {type: 'text/plain;charset=utf-8'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = prefix + slug + '.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function closeScriptResultModal() {
    var modal = document.getElementById('script-result-modal');
    if (modal) {
        modal.remove();
        // AJAX refresh of file panel instead of full page reload
        var filesPanel = document.querySelector('.files-panel, .project-files, [data-files-panel]');
        if (filesPanel && window.__CURRENT_PROJECT_ID) {
            api('/api/health').then(() => {
                if (typeof reloadWithProject === 'function') reloadWithProject();
            }).catch(() => {
                if (typeof reloadWithProject === 'function') reloadWithProject();
            });
        } else if (typeof reloadWithProject === 'function') {
            reloadWithProject();
        }
    }
}


/* ── Score All ───────────────────────────────────────── */

function scoreAll() {
    const btn = document.getElementById('score-btn');
    btn.disabled = true;
    btn.textContent = 'Pontuando...';

    showProgressModal('Pontuando Titulos');
    updateProgress(10, 'Analisando titulos no YouTube e Google Trends...');

    const countries = document.getElementById('country-select').value;
    const projectParam = window.__CURRENT_PROJECT_ID ? '&project=' + encodeURIComponent(window.__CURRENT_PROJECT_ID) : '';

    // Safari-compatible timeout (AbortSignal.timeout not supported < Safari 17)
    const controller = new AbortController();
    const scoreTimeout = setTimeout(() => controller.abort(), 300000);

    api('/api/score-all?countries=' + countries + '&force=true' + projectParam, {signal: controller.signal})
    .then(r => r.json())
    .then(data => {
        clearTimeout(scoreTimeout);
        if (data.error) {
            closeProgressModal();
            showToast('Erro: ' + data.error, 'error');
            btn.disabled = false;
            btn.textContent = 'Pontuar Todos';
        } else {
            updateProgress(100, data.scored + ' titulos pontuados!' + (data.errors ? ' (' + data.errors + ' erros)' : ''));
            showToast(data.scored + ' titulos pontuados!', 'success');
            setTimeout(() => { closeProgressModal(); reloadWithProject(); }, 1500);
        }
    })
    .catch(e => {
        clearTimeout(scoreTimeout);
        closeProgressModal();
        showToast('Erro na pontuacao', 'error');
        btn.disabled = false;
        btn.textContent = 'Pontuar Todos';
    });
}
