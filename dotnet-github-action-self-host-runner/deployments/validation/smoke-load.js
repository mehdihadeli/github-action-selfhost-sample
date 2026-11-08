import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 5,
  duration: '20s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  const baseUrl = __ENV.BASE_URL.replace(/\/$/, '');
  const response = http.get(`${baseUrl}/weatherforecast`);
  check(response, {
    'HTTP 200': result => result.status === 200,
    'five forecasts': result => {
      try {
        const forecasts = result.json();
        return Array.isArray(forecasts) && forecasts.length === 5;
      } catch {
        return false;
      }
    },
  });
  sleep(1);
}