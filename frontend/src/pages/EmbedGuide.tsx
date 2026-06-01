import React, { useState } from 'react';

const EmbedGuide: React.FC = () => {
  const [selectedMethod, setSelectedMethod] = useState('html');
  const [trackingId, setTrackingId] = useState('your-website');
  
  const baseUrl = window.location.origin;
  
  // Generate JavaScript tracking code (JS-only)
  const generateTrackingCode = (tid: string) => {
    return `<!-- CrawlDoctor JavaScript Tracking -->
<script src="${baseUrl}/track/js?tid=${tid}" async></script>`;
  };

  const trackingCode = generateTrackingCode(trackingId);

  const headInjection = `<!-- Add this to your HTML <head> section -->
${trackingCode}`;

  const ghostInjection = `<!-- Add this to Ghost Admin → Code Injection → Site Header -->
${trackingCode}`;

  const wordpressInjection = `<!-- Add this to WordPress → Appearance → Theme Editor → header.php -->
${trackingCode}`;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div className="text-center">
        <h1 className="text-3xl font-bold text-gray-900 mb-4">Embed Tracking Code</h1>
        <p className="text-lg text-gray-600">
          Add this single line of JavaScript to track visitors on your website
        </p>
      </div>

      {/* Tracking ID Input */}
      <div className="bg-blue-50 p-6 rounded-lg">
        <h2 className="text-xl font-semibold text-blue-900 mb-4">Customize Your Tracking</h2>
        <div className="flex items-center space-x-4">
          <label className="text-blue-800 font-medium">Tracking ID:</label>
          <input
            type="text"
            value={trackingId}
            onChange={(e) => setTrackingId(e.target.value)}
            className="border border-blue-300 rounded-md px-3 py-2 flex-1 max-w-md"
            placeholder="Enter your website identifier"
          />
        </div>
        <p className="text-sm text-blue-700 mt-2">
          Use a unique identifier like "blog", "main-site", or "landing-page"
        </p>
      </div>

      {/* Tracking Code Display */}
      <div className="bg-gray-50 p-6 rounded-lg">
        <h2 className="text-xl font-semibold text-gray-800 mb-4">Your Tracking Code</h2>
        <div className="bg-white p-4 rounded border max-h-64 overflow-y-auto">
          <pre className="text-sm text-gray-800 whitespace-pre-wrap">{trackingCode}</pre>
        </div>
        <p className="text-sm text-gray-600 mt-2">
          ✅ <strong>JavaScript tracking enabled</strong> - captures page views and form interactions
        </p>
      </div>

      {/* Installation Methods */}
      <div className="space-y-6">
        <h2 className="text-2xl font-bold text-gray-900">Installation Methods</h2>
        
        {/* Method Tabs */}
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            {[
              { id: 'html', name: 'HTML Head' },
              { id: 'ghost', name: 'Ghost Blog' },
              { id: 'wordpress', name: 'WordPress' },
              { id: 'other', name: 'Other Platforms' }
            ].map((method) => (
              <button
                key={method.id}
                onClick={() => setSelectedMethod(method.id)}
                className={`py-2 px-1 border-b-2 font-medium text-sm ${
                  selectedMethod === method.id
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {method.name}
              </button>
            ))}
          </nav>
        </div>

        {/* Method Content */}
        <div className="bg-white p-6 rounded-lg border">
          {selectedMethod === 'html' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-4">HTML Head Method</h3>
              <p className="text-gray-600 mb-4">
                Add the tracking code to the <code className="bg-gray-100 px-1 rounded">&lt;head&gt;</code> section of your HTML pages.
              </p>
              <div className="bg-gray-50 p-4 rounded">
                <pre className="text-sm text-gray-800 overflow-x-auto">{headInjection}</pre>
              </div>
            </div>
          )}

          {selectedMethod === 'ghost' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-4">Ghost Blog Method</h3>
              <p className="text-gray-600 mb-4">
                Add the tracking code to your Ghost blog's site header through the admin panel.
              </p>
              <ol className="list-decimal list-inside text-gray-600 mb-4 space-y-2">
                <li>Go to your Ghost Admin panel</li>
                <li>Navigate to Settings → Code Injection</li>
                <li>Add the code to the "Site Header" section</li>
                <li>Save the changes</li>
              </ol>
              <div className="bg-gray-50 p-4 rounded">
                <pre className="text-sm text-gray-800 overflow-x-auto">{ghostInjection}</pre>
              </div>
            </div>
          )}

          {selectedMethod === 'wordpress' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-4">WordPress Method</h3>
              <p className="text-gray-600 mb-4">
                Add the tracking code to your WordPress theme's header file.
              </p>
              <ol className="list-decimal list-inside text-gray-600 mb-4 space-y-2">
                <li>Go to WordPress Admin → Appearance → Theme Editor</li>
                <li>Select your active theme</li>
                <li>Open the header.php file</li>
                <li>Add the code before the closing <code className="bg-gray-100 px-1 rounded">&lt;/head&gt;</code> tag</li>
                <li>Update the file</li>
              </ol>
              <div className="bg-gray-50 p-4 rounded">
                <pre className="text-sm text-gray-800 overflow-x-auto">{wordpressInjection}</pre>
              </div>
            </div>
          )}

          {selectedMethod === 'other' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-800 mb-4">Other Platforms</h3>
              <p className="text-gray-600 mb-4">
                For other platforms, add the tracking code to the HTML head section of your pages.
              </p>
              <div className="space-y-4">
                <div>
                  <h4 className="font-semibold text-gray-800">Shopify</h4>
                  <p className="text-sm text-gray-600">
                    Go to Online Store → Themes → Edit code → theme.liquid and add to the head section
                  </p>
                </div>
                <div>
                  <h4 className="font-semibold text-gray-800">Squarespace</h4>
                  <p className="text-sm text-gray-600">
                    Go to Settings → Advanced → Code Injection → Header and add the code
                  </p>
                </div>
                <div>
                  <h4 className="font-semibold text-gray-800">Wix</h4>
                  <p className="text-sm text-gray-600">
                    Go to Settings → Custom Code → Add to Head and paste the code
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Features */}
      <div className="bg-blue-50 p-6 rounded-lg">
        <h2 className="text-xl font-semibold text-blue-900 mb-4">What This Tracks</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <h3 className="font-semibold text-blue-800">AI Crawlers</h3>
            <ul className="text-sm text-blue-700 space-y-1">
              <li>• ChatGPT (GPTBot)</li>
              <li>• Claude (Anthropic)</li>
              <li>• Perplexity AI</li>
              <li>• Google AI Studio</li>
              <li>• Other AI crawlers</li>
            </ul>
          </div>
          <div className="space-y-2">
            <h3 className="font-semibold text-blue-800">Human Visitors</h3>
            <ul className="text-sm text-blue-700 space-y-1">
              <li>• Desktop browsers</li>
              <li>• Mobile browsers</li>
              <li>• Search engine bots</li>
              <li>• Social media crawlers</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Verification */}
      <div className="bg-green-50 p-6 rounded-lg">
        <h2 className="text-xl font-semibold text-green-900 mb-4">Verify Installation</h2>
        <p className="text-green-800 mb-4">
          After adding the tracking code, visit your website and check the dashboard to see if visits are being recorded.
        </p>
        <div className="bg-white p-4 rounded border">
          <p className="text-sm text-gray-600">
            <strong>Note:</strong> This script is async and won't block page rendering.
          </p>
        </div>
      </div>
    </div>
  );
};

export default EmbedGuide;
