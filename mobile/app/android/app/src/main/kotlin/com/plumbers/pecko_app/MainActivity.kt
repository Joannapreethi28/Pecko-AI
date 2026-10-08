package com.plumbers.pecko_app

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

// One small channel: Dart needs nativeLibraryDir (where Android extracted libllama_server.so, the only
// place exec() is allowed) and a device line for the dashboard.
class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "pecko/native").setMethodCallHandler { call, result ->
            when (call.method) {
                "nativeLibDir" -> result.success(applicationInfo.nativeLibraryDir)
                "deviceInfo" -> {
                    val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
                    val mi = ActivityManager.MemoryInfo()
                    am.getMemoryInfo(mi)
                    result.success(mapOf(
                        "model" to "${Build.MANUFACTURER} ${Build.MODEL}",
                        "soc" to (if (Build.VERSION.SDK_INT >= 31) Build.SOC_MODEL else Build.HARDWARE),
                        "android" to Build.VERSION.RELEASE,
                        "sdk" to Build.VERSION.SDK_INT,
                        "totalMem" to mi.totalMem,
                        "availMem" to mi.availMem,
                        "cpus" to Runtime.getRuntime().availableProcessors()
                    ))
                }
                else -> result.notImplemented()
            }
        }
    }
}
