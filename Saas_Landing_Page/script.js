const form = document.getElementsByClassName('form-signin')[0];
const showAlert = (cssClass, message) => {
  const html = `
    <div class="alert alert-${cssClass} alert-dismissible" role="alert" style="max-height: 400px; overflow-y: auto; text-align: left;">
        <div>${message}</div>
        <button class="close" type="button" data-dismiss="alert" aria-label="Close" style="position: absolute; right: 15px; top: 10px;">
            <span aria-hidden="true">×</span>
        </button>
    </div>`;
  document.querySelector('#alert').innerHTML = html;
  window.scrollTo({ top: 0, behavior: 'smooth' });
};
const formToJSON = (elements) => [].reduce.call(elements, (data, element) => {
  data[element.name] = element.value;
  return data;
}, {});
const getUrlParameter = (name) => {
  name = name.replace(/[\[]/, '\\[').replace(/[\]]/, '\\]');
  const regex = new RegExp(`[\\?&]${name}=([^&#]*)`);
  const results = regex.exec(location.search);
  return results === null ? '' : decodeURIComponent(results[1].replace(/\+/g, ' '));
};
const handleFormSubmit = (event) => {
  event.preventDefault();
  const regToken = getUrlParameter('x-amzn-marketplace-token');
  if (!regToken) {
    showAlert('danger',
      'Registration Token Missing. Please go to AWS Marketplace and follow the instructions to set up your account!');
  } else {
    const data = formToJSON(form.elements);
    // API Gateway expects "marketplace_token" instead of "regToken"
    data.marketplace_token = regToken;

    // API Call to the new Serverless API Gateway endpoint
    const lambdaUrl = 'https://penuu7szkh.execute-api.eu-central-1.amazonaws.com/Prod/marketplace/register/';
    
    fetch(lambdaUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    })
    .then(async response => {
      if (response.ok) {
         showAlert('primary', "Registration successful! Environment provisioning has started.");
      } else {
         const errData = await response.json().catch(()=>({}));
         showAlert('danger', "Error during registration: " + (errData.error || response.status));
      }
      console.log('API Gateway registration status:', response.status);
    })
    .catch(error => {
      showAlert('danger', "Network error occurred.");
      console.error('API Gateway registration error:', error);
    });
  }
};
form.addEventListener('submit', handleFormSubmit);
const regToken = getUrlParameter('x-amzn-marketplace-token');
if (!regToken) {
  showAlert('danger', 'Registration Token Missing. Please go to AWS Marketplace and follow the instructions to set up your account!');
}
