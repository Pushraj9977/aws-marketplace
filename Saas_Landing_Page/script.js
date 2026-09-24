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
  const postUrl = `/subscriber`;
  const regToken = getUrlParameter('x-amzn-marketplace-token');
  if (!regToken) {
    showAlert('danger',
      'Registration Token Missing. Please go to AWS Marketplace and follow the instructions to set up your account!');
  } else {
    const data = formToJSON(form.elements);
    data.regToken = regToken;
    
    // Original API Call to /subscriber
    const xhr = new XMLHttpRequest();
    xhr.open('POST', postUrl, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.send(JSON.stringify(data));
    xhr.onreadystatechange = () => {
      if (xhr.readyState == XMLHttpRequest.DONE) {
        showAlert('primary', xhr.responseText);
        console.log(JSON.stringify(xhr.responseText));
      }
    };

    // Parallel Async API Call to Lambda / API Gateway REST Endpoint
    const lambdaUrl = 'https://m7gj3gbagk.execute-api.eu-central-1.amazonaws.com/prod/subscriber';
    const apiKey = 'MarketplaceApiKey123!';
    
    fetch(lambdaUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey
      },
      body: JSON.stringify(data)
    })
    .then(response => {
      console.log('Secure APIGW async registration status:', response.status);
    })
    .catch(error => {
      console.error('Secure APIGW async registration error:', error);
    });
  }
};
form.addEventListener('submit', handleFormSubmit);
const regToken = getUrlParameter('x-amzn-marketplace-token');
if (!regToken) {
  showAlert('danger', 'Registration Token Missing. Please go to AWS Marketplace and follow the instructions to set up your account!');
}
