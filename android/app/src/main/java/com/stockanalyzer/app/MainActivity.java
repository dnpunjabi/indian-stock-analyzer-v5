package com.stockanalyzer.app;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.BridgeActivity;
import java.util.ArrayList;
import java.util.Locale;
import java.util.Set;
import android.speech.tts.Voice;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends BridgeActivity {
    private WebAppInterface printInterface;
    private SpeechInterface speechInterface;
    private TtsInterface ttsInterface;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
    }
    
    @Override
    public void onStart() {
        super.onStart();
        WebView webView = this.bridge.getWebView();
        if (webView != null) {
            webView.clearCache(true);
            printInterface = new WebAppInterface(this, webView);
            speechInterface = new SpeechInterface(this, webView);
            ttsInterface = new TtsInterface(this, webView);

            webView.addJavascriptInterface(printInterface, "AndroidPrint");
            webView.addJavascriptInterface(speechInterface, "AndroidSpeech");
            webView.addJavascriptInterface(ttsInterface, "AndroidTts");
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == 101 && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            WebView webView = this.bridge.getWebView();
            if (webView != null) {
                webView.post(new Runnable() {
                    @Override
                    public void run() {
                        webView.evaluateJavascript("window.AndroidSpeech.startListening()", null);
                    }
                });
            }
        }
    }
}

class WebAppInterface {
    Context mContext;
    WebView mWebView;

    WebAppInterface(Context c, WebView w) {
        mContext = c;
        mWebView = w;
    }

    @JavascriptInterface
    public void print(final String docName) {
        mWebView.post(new Runnable() {
            @Override
            public void run() {
                PrintManager printManager = (PrintManager) mContext.getSystemService(Context.PRINT_SERVICE);
                String name = (docName != null && !docName.isEmpty()) ? docName : "Stock Analyzer Report";
                PrintDocumentAdapter printAdapter = mWebView.createPrintDocumentAdapter(name);
                printManager.print(name, printAdapter, new PrintAttributes.Builder().build());
            }
        });
    }
}

class SpeechInterface {
    MainActivity mActivity;
    WebView mWebView;
    SpeechRecognizer mSpeechRecognizer;
    Intent mSpeechRecognizerIntent;

    SpeechInterface(MainActivity a, WebView w) {
        mActivity = a;
        mWebView = w;
        
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                mSpeechRecognizer = SpeechRecognizer.createSpeechRecognizer(mActivity);
                mSpeechRecognizerIntent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                mSpeechRecognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                mSpeechRecognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-IN");

                mSpeechRecognizer.setRecognitionListener(new RecognitionListener() {
                    @Override
                    public void onReadyForSpeech(Bundle params) {
                        sendToJs("window.onAndroidSpeechStart()");
                    }
                    @Override
                    public void onBeginningOfSpeech() {}
                    @Override
                    public void onRmsChanged(float rmsdB) {}
                    @Override
                    public void onBufferReceived(byte[] buffer) {}
                    @Override
                    public void onEndOfSpeech() {
                        sendToJs("window.onAndroidSpeechEnd()");
                    }
                    @Override
                    public void onError(int error) {
                        String errorMsg = "Speech recognition error " + error;
                        sendToJs("window.onAndroidSpeechError('" + errorMsg + "')");
                    }
                    @Override
                    public void onResults(Bundle results) {
                        ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                        if (matches != null && matches.size() > 0) {
                            String speechText = matches.get(0).replace("'", "\\'");
                            sendToJs("window.onAndroidSpeechResult('" + speechText + "')");
                        }
                    }
                    @Override
                    public void onPartialResults(Bundle partialResults) {}
                    @Override
                    public void onEvent(int eventType, Bundle params) {}
                });
            }
        });
    }

    private void sendToJs(final String script) {
        mWebView.post(new Runnable() {
            @Override
            public void run() {
                mWebView.evaluateJavascript(script, null);
            }
        });
    }

    @JavascriptInterface
    public void startListening() {
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (ContextCompat.checkSelfPermission(mActivity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    ActivityCompat.requestPermissions(mActivity, new String[]{Manifest.permission.RECORD_AUDIO}, 101);
                } else {
                    mSpeechRecognizer.startListening(mSpeechRecognizerIntent);
                }
            }
        });
    }

    @JavascriptInterface
    public void stopListening() {
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                mSpeechRecognizer.stopListening();
            }
        });
    }
}

class TtsInterface implements TextToSpeech.OnInitListener {
    MainActivity mActivity;
    WebView mWebView;
    TextToSpeech mTts;
    boolean mInitialized = false;

    TtsInterface(MainActivity a, WebView w) {
        mActivity = a;
        mWebView = w;
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                mTts = new TextToSpeech(mActivity, TtsInterface.this);
            }
        });
    }

    @Override
    public void onInit(int status) {
        if (status == TextToSpeech.SUCCESS) {
            int result = mTts.setLanguage(new Locale("en", "IN"));
            if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                android.util.Log.w("StockAnalyzerTTS", "Locale en-IN not supported, falling back to US locale.");
                result = mTts.setLanguage(Locale.US);
                if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
                    android.util.Log.w("StockAnalyzerTTS", "Locale US not supported, falling back to default locale.");
                    mTts.setLanguage(Locale.getDefault());
                }
            }
            mInitialized = true;
            mTts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override
                public void onStart(String utteranceId) {}
                @Override
                public void onDone(final String utteranceId) {
                    if (!utteranceId.contains("_part_")) {
                        mWebView.post(new Runnable() {
                            @Override
                            public void run() {
                                mWebView.evaluateJavascript("window.onAndroidTtsDone()", null);
                            }
                        });
                    }
                }
                @Override
                public void onError(String utteranceId) {
                    android.util.Log.e("StockAnalyzerTTS", "TTS Utterance error: " + utteranceId);
                }
            });
        } else {
            android.util.Log.e("StockAnalyzerTTS", "TTS Initialization failed with status: " + status);
        }
    }

    @JavascriptInterface
    public void speak(final String text, final String utteranceId) {
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (mInitialized) {
                    int maxLength = 2000;
                    ArrayList<String> chunks = new ArrayList<>();
                    String[] paragraphs = text.split("\n");
                    for (String p : paragraphs) {
                        p = p.trim();
                        if (p.isEmpty()) continue;
                        
                        if (p.length() > maxLength) {
                            int start = 0;
                            while (start < p.length()) {
                                int end = Math.min(start + maxLength, p.length());
                                chunks.add(p.substring(start, end));
                                start = end;
                            }
                        } else {
                            chunks.add(p);
                        }
                    }
                    
                    if (chunks.isEmpty()) return;
                    
                    for (int i = 0; i < chunks.size(); i++) {
                        String chunk = chunks.get(i);
                        String chunkId = (i == chunks.size() - 1) ? utteranceId : utteranceId + "_part_" + i;
                        Bundle params = new Bundle();
                        params.putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, chunkId);
                        int queueMode = (i == 0) ? TextToSpeech.QUEUE_FLUSH : TextToSpeech.QUEUE_ADD;
                        mTts.speak(chunk, queueMode, params, chunkId);
                    }
                } else {
                    android.util.Log.e("StockAnalyzerTTS", "TTS speak called but not initialized yet.");
                }
            }
        });
    }

    @JavascriptInterface
    public void stop() {
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (mInitialized) {
                    mTts.stop();
                }
            }
        });
    }

    @JavascriptInterface
    public void setSpeechRate(final float rate) {
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (mInitialized) {
                    mTts.setSpeechRate(rate);
                }
            }
        });
    }

    @JavascriptInterface
    public String getNativeEnglishIndiaVoices() {
        if (mTts == null) return "[]";
        JSONArray arr = new JSONArray();
        try {
            Set<Voice> voices = mTts.getVoices();
            if (voices != null) {
                for (Voice voice : voices) {
                    if (voice.getLocale() != null && 
                        "en".equalsIgnoreCase(voice.getLocale().getLanguage())) {
                        JSONObject obj = new JSONObject();
                        obj.put("name", voice.getName());
                        
                        String country = voice.getLocale().getCountry();
                        obj.put("country", country != null ? country : "");
                        
                        // Heuristic determination of gender based on voice name suffix/components
                        String nameLower = voice.getName().toLowerCase();
                        String gender = "female"; // Default fallback
                        
                        if (nameLower.contains("gnd") || nameLower.contains("cxx") || nameLower.contains("tct") || nameLower.contains("male") || nameLower.contains("ene") || nameLower.contains("gde") || nameLower.contains("david") || nameLower.contains("ravi") || nameLower.contains("rishi") || nameLower.contains("prabhat") || nameLower.contains("harman") || nameLower.contains("george") || nameLower.contains("mark") || nameLower.contains("daniel") || nameLower.contains("richard") || nameLower.contains("james") || nameLower.contains("oliver") || nameLower.contains("peter") || nameLower.contains("harry") || nameLower.contains("john") || nameLower.contains("steven") || nameLower.contains("stefan")) {
                            gender = "male";
                        }
                        obj.put("gender", gender);
                        arr.put(obj);
                    }
                }
            }
        } catch (Exception e) {
            android.util.Log.e("StockAnalyzerTTS", "Error fetching native voices: " + e.getMessage());
        }
        return arr.toString();
    }

    @JavascriptInterface
    public void setNativeVoice(final String voiceName) {
        mActivity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (mInitialized && mTts != null) {
                    try {
                        Set<Voice> voices = mTts.getVoices();
                        if (voices != null) {
                            for (Voice voice : voices) {
                                if (voice.getName().equals(voiceName)) {
                                    mTts.setVoice(voice);
                                    android.util.Log.i("StockAnalyzerTTS", "Set native voice to: " + voiceName);
                                    break;
                                }
                            }
                        }
                    } catch (Exception e) {
                        android.util.Log.e("StockAnalyzerTTS", "Error setting native voice: " + e.getMessage());
                    }
                }
            }
        });
    }
}
