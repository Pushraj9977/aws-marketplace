const form = document.getElementsByClassName('form-signin')[0];
const statusNode = document.getElementById('status');
const bodyConfig = document.body.dataset.apiBaseUrl || '';
const apiBaseUrl = (window.LANDING_API_BASE_URL || bodyConfig).replace(/\/$/, '');
const resolveUrl = `${apiBaseUrl}/marketplace/resolve`;
const registerUrl = `${apiBaseUrl}/marketplace/register`;
let resolvedCustomer = null;

const showAlert = (cssClass, message) => {
  const html = `
    <div class="alert alert-${cssClass} alert-dismissible" role="alert">
        <strong>${message}</strong>
        <button class="close" type="button" data-dismiss="alert" aria-label="Close">
            <span aria-hidden="true">×</span>
        </button>
    </div>`;
  document.querySelector('#alert').innerHTML += html;
};
const setStatus = (message) => {
  statusNode.textContent = message;
};
const formToJSON = (elements) => [].reduce.call(elements, (data, element) => {
  if (element.name) {
    data[element.name] = element.value;
  }
  return data;
}, {});
const getUrlParameter = (name) => {
  name = name.replace(/[\[]/, '\\[').replace(/[\]]/, '\\]');
  const regex = new RegExp(`[\\?&]${name}=([^&#]*)`);
  const results = regex.exec(location.search);
  return results === null ? '' : decodeURIComponent(results[1].replace(/\+/g, ' '));
};
const regToken = getUrlParameter('x-amzn-marketplace-token');

const postJson = async (url, payload) => {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `Request failed with status ${response.status}`);
  }
  return body;
};

const verifyMarketplaceToken = async () => {
  if (!regToken) {
    showAlert('danger', 'Registration token missing. Return to AWS Marketplace and launch setup again.');
    setStatus('Waiting for a valid Marketplace token.');
    form.querySelector('button[type="submit"]').disabled = true;
    return;
  }

  try {
    setStatus('Verifying your AWS Marketplace subscription...');
    const result = await postJson(resolveUrl, { marketplace_token: regToken });
    resolvedCustomer = result.customer;
    form.querySelector('button[type="submit"]').disabled = false;
    setStatus(`Subscription verified for product ${resolvedCustomer.product_code}.`);
    showAlert('success', 'AWS Marketplace subscription verified. You can finish onboarding below.');
  } catch (error) {
    form.querySelector('button[type="submit"]').disabled = true;
    setStatus('We could not verify the AWS Marketplace token.');
    showAlert('danger', error.message);
  }
};

const handleFormSubmit = async (event) => {
  event.preventDefault();
  if (!resolvedCustomer) {
    showAlert('danger', 'Marketplace subscription has not been verified yet.');
    return;
  }

  try {
    const data = formToJSON(form.elements);
    data.marketplace_token = regToken;
    setStatus('Starting tenant provisioning...');
    const result = await postJson(registerUrl, data);
    setStatus('Provisioning started successfully.');
    showAlert(
      'success',
      result.message || 'Your environment is being built. We will email you when it is ready.'
    );
  } catch (error) {
    setStatus('Provisioning could not be started.');
    showAlert('danger', error.message);
  }
};

form.addEventListener('submit', handleFormSubmit);
form.querySelector('button[type="submit"]').disabled = true;
verifyMarketplaceToken();
