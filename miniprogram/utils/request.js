const {
  clearSession,
  getApiBase,
  getSession,
} = require('./session');

function errorMessage(payload, fallback) {
  if (!payload) return fallback;
  if (payload.message) return payload.message;
  if (payload.error) return payload.error;
  return fallback;
}

function request(options) {
  const session = getSession();
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${options.apiBase || getApiBase()}${options.path}`,
      method: options.method || 'GET',
      data: options.data,
      timeout: options.timeout || 15000,
      header: {
        'content-type': 'application/json',
        ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
        ...(options.header || {}),
      },
      success(response) {
        if (response.statusCode === 401) {
          clearSession();
          wx.reLaunch({ url: '/pages/login/index' });
          reject(new Error('登录已过期，请重新登录'));
          return;
        }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(errorMessage(response.data, `请求失败 (${response.statusCode})`)));
          return;
        }
        resolve(response.data);
      },
      fail(error) {
        reject(new Error(error.errMsg || '网络连接失败'));
      },
    });
  });
}

function upload(options) {
  const session = getSession();
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${getApiBase()}${options.path}`,
      filePath: options.filePath,
      name: 'file',
      formData: options.formData || {},
      timeout: options.timeout || 30000,
      header: session ? { Authorization: `Bearer ${session.token}` } : {},
      success(response) {
        let data = {};
        try {
          data = JSON.parse(response.data || '{}');
        } catch {
          data = { message: response.data };
        }
        if (response.statusCode === 401) {
          clearSession();
          wx.reLaunch({ url: '/pages/login/index' });
          reject(new Error('登录已过期，请重新登录'));
          return;
        }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(errorMessage(data, `上传失败 (${response.statusCode})`)));
          return;
        }
        resolve(data);
      },
      fail(error) {
        reject(new Error(error.errMsg || '照片上传失败'));
      },
    });
  });
}

module.exports = {
  request,
  upload,
};
