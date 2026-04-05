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
        overlay.remove();
        onConfirm();
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


/* ── Generate Script ─────────────────────────────────── */

function generateScript(id, title) {
    showConfirm('Gerar Roteiro', 'Gerar roteiro para:<br><br><strong>"' + title + '"</strong><br><br>Usa a API (laozhang.ai) e pode levar 1-2 minutos.', () => {
        const btn = document.querySelector('#idea-' + id + ' .gen-btn');
        if (btn) { btn.disabled = true; btn.textContent = '...'; }

        showProgressModal('Gerando Roteiro');
        updateProgress(15, 'Preparando prompt...');

        // Simulate progress
        let step = 0;
        const msgs = ['Analisando SOP do canal...', 'Escrevendo roteiro...', 'Finalizando...'];
        const scriptInterval = setInterval(() => {
            if (step < msgs.length) {
                updateProgress(30 + step * 25, msgs[step]);
                step++;
            } else {
                clearInterval(scriptInterval);
            }
        }, 8000);

        apiPost('/api/generate-script', {id: id})
        .then(r => r.json())
        .then(data => {
            clearInterval(scriptInterval);
            if (data.ok) {
                updateProgress(100, 'Roteiro gerado! ' + data.script_words + ' palavras (' + data.duration_estimate + ')');
                showToast('Roteiro gerado! ' + data.script_words + ' palavras', 'success', 5000);
                setTimeout(() => { closeProgressModal(); reloadWithProject(); }, 2000);
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
