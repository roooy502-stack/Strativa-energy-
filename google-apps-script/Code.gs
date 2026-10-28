/**
 * Strativa Energy monthly Google performance report.
 * Read-only against Google Analytics 4 and Search Console.
 *
 * First-time setup:
 * 1. Open this project at script.google.com.
 * 2. In Project Settings, set the timezone to Australia/Melbourne.
 * 3. Run setupMonthlyTrigger once and approve the requested read-only scopes.
 * 4. Run generateMonthlyReport once to test.
 */

const CONFIG = {
  siteUrl: 'https://strativaenergy.com.au/',
  ga4PropertyId: '', // Optional. Leave blank to auto-discover a web property.
  driveFolderName: 'Strativa Energy Monthly Reports',
  timezone: 'Australia/Melbourne',
  topRows: 25
};

function setupMonthlyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'generateMonthlyReport') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('generateMonthlyReport')
    .timeBased()
    .onMonthDay(1)
    .atHour(8)
    .create();
  Logger.log('Monthly trigger created for day 1 at approximately 08:00.');
}

function generateMonthlyReport() {
  const period = getPreviousCompleteMonth_();
  const previous = getPreviousMonth_(period);
  const gaPropertyId = CONFIG.ga4PropertyId || discoverGa4Property_();
  const ga = collectGa4_(gaPropertyId, period, previous);
  const gsc = collectSearchConsole_(period, previous);
  const report = buildReport_(period, previous, gaPropertyId, ga, gsc);
  saveReport_(report, period.label);
  Logger.log(JSON.stringify({label: period.label, folder: CONFIG.driveFolderName}));
}

function getPreviousCompleteMonth_() {
  const now = new Date();
  const current = Utilities.formatDate(now, CONFIG.timezone, 'yyyy-MM');
  const parts = current.split('-').map(Number);
  const date = new Date(Date.UTC(parts[0], parts[1] - 2, 1));
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth() + 1;
  return {label: year + '-' + pad_(month), start: year + '-' + pad_(month) + '-01', end: year + '-' + pad_(month) + '-' + daysInMonth_(year, month)};
}

function getPreviousMonth_(period) {
  const parts = period.start.split('-').map(Number);
  const date = new Date(Date.UTC(parts[0], parts[1] - 2, 1));
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth() + 1;
  return {label: year + '-' + pad_(month), start: year + '-' + pad_(month) + '-01', end: year + '-' + pad_(month) + '-' + daysInMonth_(year, month)};
}

function discoverGa4Property_() {
  const accounts = fetchJson_('https://analyticsadmin.googleapis.com/v1beta/accounts?pageSize=100');
  const accountRows = accounts.accounts || [];
  for (let i = 0; i < accountRows.length; i++) {
    const accountId = accountRows[i].name;
    const properties = fetchJson_('https://analyticsadmin.googleapis.com/v1beta/properties?filter=parent:' + encodeURIComponent(accountId) + '&pageSize=100');
    const rows = properties.properties || [];
    for (let j = 0; j < rows.length; j++) {
      const property = rows[j];
      const streams = fetchJson_('https://analyticsadmin.googleapis.com/v1beta/' + property.name + '/dataStreams?pageSize=100');
      const webStreams = streams.dataStreams || [];
      for (let k = 0; k < webStreams.length; k++) {
        const web = webStreams[k].webStreamData;
        if (web && web.defaultUri && web.defaultUri.indexOf('strativaenergy.com.au') !== -1) {
          return property.name.replace('properties/', '');
        }
      }
    }
  }
  throw new Error('GA4 property was not auto-discovered. Set CONFIG.ga4PropertyId to the numeric property ID.');
}

function collectGa4_(propertyId, period, previous) {
  return {
    period: runGaReport_(propertyId, period),
    previous: runGaReport_(propertyId, previous),
    topPages: runGaReport_(propertyId, period, [{name: 'pagePathPlusQueryString'}], ['screenPageViews', 'sessions', 'engagementRate'], 'screenPageViews'),
    channels: runGaReport_(propertyId, period, [{name: 'sessionDefaultChannelGroup'}], ['sessions', 'totalUsers', 'engagementRate'], 'sessions'),
    devices: runGaReport_(propertyId, period, [{name: 'deviceCategory'}], ['sessions', 'totalUsers'], 'sessions')
  };
}

function runGaReport_(propertyId, period, dimensions, metrics, orderMetric) {
  const body = {
    dateRanges: [{startDate: period.start, endDate: period.end}],
    metrics: (metrics || ['totalUsers', 'sessions', 'engagedSessions', 'engagementRate', 'conversions']).map(function(name) { return {name: name}; }),
    dimensionals: undefined
  };
  delete body.dimensionals;
  if (dimensions) body.dimensions = dimensions;
  if (orderMetric) body.orderBys = [{metric: {metricName: orderMetric}, desc: true}];
  if (dimensions) body.limit = CONFIG.topRows;
  return fetchJson_('https://analyticsdata.googleapis.com/v1beta/properties/' + encodeURIComponent(propertyId) + ':runReport', body, true);
}

function collectSearchConsole_(period, previous) {
  return {
    period: runGscQuery_(period),
    previous: runGscQuery_(previous),
    topQueries: runGscQuery_(period, ['query']),
    topPages: runGscQuery_(period, ['page'])
  };
}

function runGscQuery_(period, dimensions) {
  const endpoint = 'https://searchconsole.googleapis.com/webmasters/v3/sites/' + encodeURIComponent(CONFIG.siteUrl) + '/searchAnalytics/query';
  return fetchJson_(endpoint, {
    startDate: period.start,
    endDate: period.end,
    dimensions: dimensions || [],
    rowLimit: CONFIG.topRows,
    dataState: 'final'
  }, true);
}

function buildReport_(period, previous, propertyId, ga, gsc) {
  return {
    generatedAt: new Date().toISOString(),
    site: CONFIG.siteUrl,
    period: period,
    previousPeriod: previous,
    ga4: {propertyId: propertyId, data: ga},
    searchConsole: {siteUrl: CONFIG.siteUrl, data: gsc},
    privacy: 'Aggregated performance data only; no user-level data is collected or stored.',
    notes: ['This report is read-only.', 'FAQ, SEO, and website changes are never published by this script.']
  };
}

function saveReport_(report, label) {
  const folder = getOrCreateFolder_(CONFIG.driveFolderName);
  const json = JSON.stringify(report, null, 2);
  const markdown = renderMarkdown_(report);
  folder.createFile('strativa-google-performance-' + label + '.json', json, MimeType.PLAIN_TEXT);
  folder.createFile('strativa-google-performance-' + label + '.md', markdown, MimeType.PLAIN_TEXT);
}

function renderMarkdown_(report) {
  const gaPeriod = report.ga4.data.period || {};
  const gaPrevious = report.ga4.data.previous || {};
  const gscPeriod = report.searchConsole.data.period || {};
  const gscPrevious = report.searchConsole.data.previous || {};
  const lines = [
    '# Strativa Energy Monthly Google Performance Report', '',
    '- Period: `' + report.period.label + '`',
    '- Previous period: `' + report.previousPeriod.label + '`',
    '- Site: ' + report.site, '',
    '## Google Analytics 4', '',
    '| Metric | Current | Previous | Change |', '|---|---:|---:|---:|',
    metricRow_('Total users', metric_(gaPeriod, 'totalUsers'), metric_(gaPrevious, 'totalUsers')),
    metricRow_('Sessions', metric_(gaPeriod, 'sessions'), metric_(gaPrevious, 'sessions')),
    metricRow_('Engaged sessions', metric_(gaPeriod, 'engagedSessions'), metric_(gaPrevious, 'engagedSessions')),
    metricRow_('Engagement rate', metric_(gaPeriod, 'engagementRate'), metric_(gaPrevious, 'engagementRate')),
    metricRow_('Conversions', metric_(gaPeriod, 'conversions'), metric_(gaPrevious, 'conversions')), '',
    '## Google Search Console', '',
    '| Metric | Current | Previous | Change |', '|---|---:|---:|---:|',
    metricRow_('Clicks', gscMetric_(gscPeriod, 'clicks'), gscMetric_(gscPrevious, 'clicks')),
    metricRow_('Impressions', gscMetric_(gscPeriod, 'impressions'), gscMetric_(gscPrevious, 'impressions')),
    metricRow_('CTR', gscMetric_(gscPeriod, 'ctr'), gscMetric_(gscPrevious, 'ctr')),
    metricRow_('Average position', gscMetric_(gscPeriod, 'position'), gscMetric_(gscPrevious, 'position')), '',
    '## Review Notes', '',
    '- Review traffic, search visibility, and landing-page changes before making SEO decisions.',
    '- This report is informational and does not change the website.', ''
  ];
  return lines.join('\n');
}

function metric_(response, name) {
  const row = response && response.rows && response.rows[0];
  const headers = response && response.metricHeaders || [];
  const index = headers.findIndex(function(header) { return header.name === name; });
  const value = row && row.metricValues && index >= 0 ? row.metricValues[index] : null;
  if (value && value.value !== undefined) return Number(value.value);
  if (response && response[name] !== undefined) return Number(response[name]);
  return 0;
}

function gscMetric_(response, name) {
  const row = response && response.rows && response.rows[0];
  if (row && row[name] !== undefined) return Number(row[name]);
  return response && response[name] !== undefined ? Number(response[name]) : 0;
}

function metricRow_(label, current, previous) {
  const change = previous ? ((current - previous) / previous * 100).toFixed(1) + '%' : 'n/a';
  return '| ' + label + ' | ' + formatMetric_(current) + ' | ' + formatMetric_(previous) + ' | ' + change + ' |';
}

function formatMetric_(value) { return typeof value === 'number' ? value.toLocaleString('en-AU', {maximumFractionDigits: 3}) : value; }
function pad_(number) { return String(number).padStart(2, '0'); }
function daysInMonth_(year, month) { return new Date(Date.UTC(year, month, 0)).getUTCDate(); }

function getOrCreateFolder_(name) {
  const folders = DriveApp.getFoldersByName(name);
  return folders.hasNext() ? folders.next() : DriveApp.createFolder(name);
}

function fetchJson_(url, body, isPost) {
  const options = {
    method: isPost ? 'post' : 'get',
    muteHttpExceptions: true,
    headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()}
  };
  if (isPost) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(body);
  }
  const response = UrlFetchApp.fetch(url, options);
  const code = response.getResponseCode();
  const text = response.getContentText();
  if (code < 200 || code >= 300) throw new Error('Google API request failed (' + code + '): ' + text.slice(0, 500));
  return text ? JSON.parse(text) : {};
}
