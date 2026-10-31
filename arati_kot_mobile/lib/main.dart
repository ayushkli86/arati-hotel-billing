import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;
import 'package:multicast_dns/multicast_dns.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Optional fallback URL baked in at build time.
///
/// The app normally discovers the server on the local network (mDNS or the
/// `arati.local` name), so a new Wi-Fi does not need a new build:
/// `flutter build apk --dart-define=SERVER_URL=http://192.168.1.20:8000`
const String kServerUrl = String.fromEnvironment('SERVER_URL');

/// mDNS service advertised by `arati-mdns.service` on the hotel server.
const String kServerService = '_arati-kot._tcp.local';
const int kServerPort = 8000;

/// System-tray alerts when a new order (KOT) reaches this device.
class NotificationService {
  NotificationService._();

  static final NotificationService instance = NotificationService._();

  static const String _channelId = 'arati_orders_v2';
  static const String _channelName = 'Arati order alerts';
  static const String _channelDescription =
      'Plays the Arati order bell when a new order (KOT) is placed';
  static const RawResourceAndroidNotificationSound _sound =
      RawResourceAndroidNotificationSound('arati_alert');
  static final Int64List _vibration =
      Int64List.fromList([0, 400, 180, 400, 180, 900]);

  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  final Set<int> _shown = {};
  bool _ready = false;

  Future<void> init() async {
    const android = AndroidInitializationSettings('ic_arati_order');
    const darwin = DarwinInitializationSettings();
    const settings = InitializationSettings(
      android: android,
      iOS: darwin,
      macOS: darwin,
    );
    try {
      await _plugin.initialize(settings: settings);
      if (Platform.isAndroid) {
        final implementation = _plugin
            .resolvePlatformSpecificImplementation<
                AndroidFlutterLocalNotificationsPlugin>();
        final channel = AndroidNotificationChannel(
          _channelId,
          _channelName,
          description: _channelDescription,
          importance: Importance.max,
          playSound: true,
          sound: _sound,
          enableVibration: true,
          vibrationPattern: _vibration,
        );
        await implementation?.deleteNotificationChannel(
          channelId: 'arati_orders',
        );
        await implementation?.createNotificationChannel(channel);
      }
      _ready = true;
    } catch (_) {
      _ready = false;
    }
  }

  Future<void> requestPermission() async {
    if (!_ready) return;
    try {
      if (Platform.isAndroid) {
        await _plugin
            .resolvePlatformSpecificImplementation<
                AndroidFlutterLocalNotificationsPlugin>()
            ?.requestNotificationsPermission();
      } else if (Platform.isIOS) {
        await _plugin
            .resolvePlatformSpecificImplementation<
                IOSFlutterLocalNotificationsPlugin>()
            ?.requestPermissions(alert: true, badge: true, sound: true);
      }
    } catch (_) {}
  }

  Future<void> showNewOrders(List<Map<String, dynamic>> kots) async {
    if (!_ready || kots.isEmpty) return;
    final fresh = <Map<String, dynamic>>[];
    for (final kot in kots) {
      final id = kot['id'];
      if (id is int && _shown.add(id)) fresh.add(kot);
    }
    if (fresh.isEmpty) return;

    final details = _details();

    if (fresh.length == 1) {
      final kot = fresh.single;
      final id = kot['id'] as int;
      await _plugin.show(
        id: id,
        title: 'New order ${_kotNumber(kot)}',
        body: _kotSummary(kot),
        notificationDetails: details,
        payload: _kotNumber(kot),
      );
      return;
    }

    final lines = fresh.take(6).map((kot) {
      return '${_kotNumber(kot)} · ${_kotSummary(kot)}';
    }).join('\n');
    final title = '${fresh.length} new orders';
    await _plugin.show(
      id: 900000 + fresh.length,
      title: title,
      body: lines,
      notificationDetails: _details(
        style: BigTextStyleInformation(lines, contentTitle: title),
      ),
      payload: title,
    );
  }

  static NotificationDetails _details({StyleInformation? style}) {
    return NotificationDetails(
      android: AndroidNotificationDetails(
        _channelId,
        _channelName,
        channelDescription: _channelDescription,
        importance: Importance.max,
        priority: Priority.high,
        playSound: true,
        sound: _sound,
        enableVibration: true,
        vibrationPattern: _vibration,
        category: AndroidNotificationCategory.message,
        icon: 'ic_arati_order',
        styleInformation: style,
      ),
      iOS: const DarwinNotificationDetails(
        presentAlert: true,
        presentBadge: true,
        presentSound: true,
      ),
      macOS: const DarwinNotificationDetails(
        presentAlert: true,
        presentSound: true,
      ),
    );
  }

  static String _kotNumber(Map<String, dynamic> kot) =>
      '${kot['kot_number'] ?? 'KOT'}';

  static String _kotSummary(Map<String, dynamic> kot) {
    final room = '${kot['room_number'] ?? ''}'.trim();
    final table = '${kot['table_number'] ?? ''}'.trim();
    final where = room.isNotEmpty
        ? 'Room $room'
        : (table.isNotEmpty ? 'Table $table' : 'Walk-in');
    final items = kot['items'];
    final count = items is List ? items.length : 0;
    final total = kot['total'];
    final amount = total is num ? ' · Rs ${total.toStringAsFixed(0)}' : '';
    return '$where · $count item${count == 1 ? '' : 's'}$amount';
  }
}

/// Finds the hotel server even when the router hands out a different IP.
class ServerConfig {
  static const String _savedKey = 'server_url';
  static const List<String> _knownNames = [
    'http://arati.local:8000',
    'http://debian.local:8000',
  ];

  static String normalize(String raw) {
    var value = raw.trim();
    if (value.isEmpty) return '';
    if (!value.startsWith('http://') && !value.startsWith('https://')) {
      value = 'http://$value';
    }
    final uri = Uri.tryParse(value);
    if (uri == null || uri.host.isEmpty) return '';
    final withPort = !uri.hasPort && uri.scheme == 'http'
        ? uri.replace(port: kServerPort)
        : uri;
    final clean = Uri(
      scheme: withPort.scheme,
      userInfo: withPort.userInfo.isEmpty ? null : withPort.userInfo,
      host: withPort.host,
      port: withPort.port,
    );
    return clean.toString();
  }

  static Future<String?> saved() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_savedKey);
  }

  static Future<void> save(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_savedKey, url);
  }

  static Future<bool> isReachable(String url, {Duration timeout = const Duration(seconds: 3)}) async {
    final client = http.Client();
    try {
      final response = await client.get(Uri.parse('$url/healthz')).timeout(timeout);
      return response.statusCode == 200;
    } catch (_) {
      return false;
    } finally {
      client.close();
    }
  }

  /// Asks the LAN which address the Arati KOT service is on right now.
  static Future<String?> discoverMdns() async {
    final client = MDnsClient();
    try {
      await client.start();
      Future<String?> lookup() async {
        await for (final ptr
            in client.lookup<PtrResourceRecord>(ResourceRecordQuery.serverPointer(kServerService))) {
          await for (final srv
              in client.lookup<SrvResourceRecord>(ResourceRecordQuery.service(ptr.domainName))) {
            await for (final ip in client.lookup<IPAddressResourceRecord>(
                ResourceRecordQuery.addressIPv4(srv.target))) {
              return 'http://${ip.address.address}:${srv.port}';
            }
          }
        }
        return null;
      }

      return await lookup().timeout(const Duration(seconds: 4));
    } catch (_) {
      return null;
    } finally {
      client.stop();
    }
  }

  /// Last resort when mDNS is unavailable (e.g. networks that use the
  /// 100.64/10 address range, where Avahi refuses to publish): probes every
  /// host on the phone's own /24 for `/healthz`.
  static Future<String?> scanLan() async {
    final prefixes = <String>{};
    try {
      final interfaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLoopback: false,
      );
      for (final iface in interfaces) {
        final name = iface.name.toLowerCase();
        if (name.startsWith('tailscale') ||
            name.startsWith('lxc') ||
            name.startsWith('docker') ||
            name.startsWith('virbr')) {
          continue;
        }
        for (final address in iface.addresses) {
          if (address.isLoopback) continue;
          final parts = address.address.split('.');
          if (parts.length == 4) {
            prefixes.add('${parts[0]}.${parts[1]}.${parts[2]}.');
          }
        }
      }
    } catch (_) {
      return null;
    }

    for (final prefix in prefixes) {
      final urls =
          List.generate(254, (i) => 'http://$prefix${i + 1}:$kServerPort');
      for (var start = 0; start < urls.length; start += 32) {
        final batch = urls.skip(start).take(32);
        final found = Completer<String?>();
        var pending = 0;
        for (final url in batch) {
          pending++;
          isReachable(url, timeout: const Duration(milliseconds: 800))
              .then((ok) {
            if (ok && !found.isCompleted) found.complete(url);
          }).whenComplete(() {
            pending--;
            if (pending == 0 && !found.isCompleted) found.complete(null);
          });
        }
        final hit = await found.future;
        if (hit != null) return hit;
      }
    }
    return null;
  }

  /// Returns the first address that answers `/healthz`, or null.
  ///
  /// Tries the current/saved address first, then the `arati.local` name, mDNS
  /// and finally a scan of the local /24, so a changed Wi-Fi only costs a few
  /// seconds.
  static Future<String?> resolve({String? preferred}) async {
    final candidates = <String>[];
    void add(String? url) {
      final normalized = normalize(url ?? '');
      if (normalized.isEmpty || candidates.contains(normalized)) return;
      candidates.add(normalized);
    }

    add(preferred);
    add(await saved());
    add(kServerUrl);
    for (final name in _knownNames) {
      add(name);
    }

    for (final url in candidates) {
      if (await isReachable(url)) {
        await save(url);
        return url;
      }
    }

    final discovered = await discoverMdns();
    if (discovered != null && await isReachable(discovered)) {
      await save(discovered);
      return discovered;
    }

    final scanned = await scanLan();
    if (scanned != null) {
      await save(scanned);
      return scanned;
    }
    return null;
  }
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await NotificationService.instance.init();
  runApp(const AratiKOTApp());
}

class AratiKOTApp extends StatefulWidget {
  const AratiKOTApp({super.key});

  @override
  State<AratiKOTApp> createState() => _AratiKOTAppState();
}

class _AratiKOTAppState extends State<AratiKOTApp> {
  ApiClient? _api;
  String? _notice;

  void _signIn(ApiClient api) {
    setState(() {
      _api = api;
      _notice = null;
    });
  }

  void _signOut() {
    setState(() {
      _api = null;
      _notice = 'Your session expired. Sign in again.';
    });
  }

  @override
  Widget build(BuildContext context) {
    final api = _api;
    return MaterialApp(
      title: 'Arati Hotel KOT',
      theme: ThemeData(primarySwatch: Colors.indigo, useMaterial3: true),
      home: api == null
          ? LoginScreen(onSignedIn: _signIn, notice: _notice)
          : KOTScreen(api: api, onSessionExpired: _signOut),
    );
  }
}

/// The server refused the call for a reason the user can act on.
class ApiFailure implements Exception {
  ApiFailure(this.message, {this.statusCode});

  final String message;

  /// Null when the server could not be reached at all.
  final int? statusCode;

  @override
  String toString() => message;
}

/// The session cookie is missing, expired or was revoked by a password change.
class SessionExpired implements Exception {}

/// Keeps the signed session cookie and CSRF token for one signed-in user.
class ApiClient {
  final Map<String, String> _cookies = {};
  final http.Client _client = http.Client();

  /// Base URL of the hotel server; updated when the Wi-Fi (and IP) changes.
  String _serverUrl = kServerUrl;

  String get serverUrl => _serverUrl;

  set serverUrl(String value) => _serverUrl = ServerConfig.normalize(value);

  /// Rotated by signing in; handed back by `/api/rooms` and `/api/menu`.
  String? csrfToken;

  String get _cookieHeader =>
      _cookies.entries.map((cookie) => '${cookie.key}=${cookie.value}').join('; ');

  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, String> headers = const {},
    String? body,
  }) async {
    try {
      return await _sendOnce(method, path, headers: headers, body: body);
    } on ApiFailure {
      rethrow;
    } on Exception catch (first) {
      // A new Wi-Fi usually means a new server IP: rediscover and retry once.
      final recovered = await ServerConfig.resolve(preferred: _serverUrl);
      if (recovered != null && recovered != _serverUrl) {
        _serverUrl = recovered;
        try {
          return await _sendOnce(method, path, headers: headers, body: body);
        } on Exception {
          // Report the original failure below.
        }
      }
      throw ApiFailure(
        'Could not reach the server at ${_serverUrl.isEmpty ? 'the hotel network' : _serverUrl} '
        '(${first.runtimeType}). Check that this phone and the server are on the same Wi-Fi.',
      );
    }
  }

  Future<http.Response> _sendOnce(
    String method,
    String path, {
    Map<String, String> headers = const {},
    String? body,
  }) async {
    if (_serverUrl.isEmpty) {
      throw ApiFailure('No server address yet. Tap the server row and enter it.');
    }
    final request = http.Request(method, Uri.parse('$_serverUrl$path'))
      // Redirects point at HTML pages: without this, a 303 to /login would be
      // followed and reported as a successful 200.
      ..followRedirects = false
      ..headers.addAll({'Accept': 'application/json', ...headers});
    if (_cookies.isNotEmpty) {
      request.headers['Cookie'] = _cookieHeader;
    }
    if (body != null) {
      request.body = body;
    }

    final streamed = await _client
        .send(request)
        .timeout(const Duration(seconds: 20));
    final response = await http.Response.fromStream(streamed);
    _storeCookies(response);
    return response;
  }

  /// `package:http` joins repeated headers with ", ", so a cookie's
  /// `Expires=Wed, 21 Oct 2015` must not be read as a second cookie.
  List<String> _splitSetCookie(String raw) {
    final parts = <String>[];
    final cookieStart = RegExp(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+=");
    for (final segment in raw.split(', ')) {
      if (parts.isNotEmpty && !cookieStart.hasMatch(segment)) {
        parts[parts.length - 1] = '${parts.last}, $segment';
      } else {
        parts.add(segment);
      }
    }
    return parts;
  }

  void _storeCookies(http.Response response) {
    final raw = response.headers['set-cookie'];
    if (raw == null) return;
    for (final part in _splitSetCookie(raw)) {
      final pair = part.split(';').first.trim();
      final separator = pair.indexOf('=');
      if (separator <= 0) continue;
      final name = pair.substring(0, separator).trim();
      final value = pair.substring(separator + 1).trim();
      if (value.isEmpty) {
        _cookies.remove(name);
      } else {
        _cookies[name] = value;
      }
    }
  }

  Future<void> signIn(String username, String password) async {
    final page = await _send('GET', '/login', headers: {'Accept': 'text/html'});
    final token =
        RegExp(r'name="csrf_token"\s+value="([^"]+)"').firstMatch(page.body)?.group(1);
    if (token == null) {
      throw ApiFailure('The server did not send a sign-in form. Check the server address.');
    }

    // Uri percent-encodes the fields, so passwords with +, & or spaces survive.
    final form = Uri(queryParameters: {
      'username': username,
      'password': password,
      'csrf_token': token,
    }).query;
    final response = await _send(
      'POST',
      '/login',
      headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'},
      body: form,
    );
    if (response.statusCode != 303) {
      throw ApiFailure(_signInError(response.statusCode), statusCode: response.statusCode);
    }
    // Signing in issues a fresh CSRF token; /api hands the new one over.
    csrfToken = null;
    await ServerConfig.save(_serverUrl);
  }

  String _signInError(int status) {
    switch (status) {
      case 401:
        return 'Username or password is incorrect.';
      case 403:
        return 'Your session expired. Sign in again.';
      case 429:
        return 'Too many sign-in attempts. Wait a few minutes and try again.';
      default:
        return 'Sign-in failed (HTTP $status).';
    }
  }

  Future<List<Map<String, dynamic>>> fetchRooms() =>
      _fetchRows('/api/rooms', 'rooms');

  Future<List<Map<String, dynamic>>> fetchMenu() =>
      _fetchRows('/api/menu', 'menu');

  /// Open tickets created by any device, not just this phone.
  Future<List<Map<String, dynamic>>> fetchOpenKots() =>
      _fetchRows('/api/kots', 'kots');

  /// Marks a ticket ready. The server answers 428 while it still needs the
  /// second confirmation, so callers retry with [confirm] set to true.
  Future<Map<String, dynamic>> cutKot(int kotId, {bool confirm = false}) async {
    if (csrfToken == null) {
      await _fetchRows('/api/kots', 'kots');
    }
    final body = _decode(await _send(
      'POST',
      '/api/kots/$kotId/cut',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: jsonEncode({'csrf_token': csrfToken, 'confirm': confirm}),
    ));
    if (body is! Map || body['kot'] is! Map) {
      throw ApiFailure('The server sent an answer this app cannot read.');
    }
    return Map<String, dynamic>.from(body['kot'] as Map);
  }

  /// Moves a ticket forward (preparing, ready, served). The server answers 428
  /// while the "ready" step still needs the second confirmation, so callers
  /// retry with [confirm] set to true.
  Future<Map<String, dynamic>> setKotStatus(
    int kotId,
    String status, {
    bool confirm = false,
  }) async {
    if (csrfToken == null) {
      await _fetchRows('/api/kots', 'kots');
    }
    final body = _decode(await _send(
      'POST',
      '/api/kots/$kotId/status',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: jsonEncode({
        'csrf_token': csrfToken,
        'status': status,
        'confirm': confirm,
      }),
    ));
    if (body is! Map || body['kot'] is! Map) {
      throw ApiFailure('The server sent an answer this app cannot read.');
    }
    return Map<String, dynamic>.from(body['kot'] as Map);
  }

  /// Deletes a ticket and reverses the room charges it posted. The server
  /// refuses tickets that have already reached an invoice.
  Future<Map<String, dynamic>> deleteKot(int kotId) async {
    if (csrfToken == null) {
      await _fetchRows('/api/kots', 'kots');
    }
    final body = _decode(await _send(
      'POST',
      '/api/kots/$kotId/delete',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: jsonEncode({'csrf_token': csrfToken, 'confirm': true}),
    ));
    if (body is! Map) {
      throw ApiFailure('The server sent an answer this app cannot read.');
    }
    return Map<String, dynamic>.from(body);
  }

  Future<List<Map<String, dynamic>>> _fetchRows(String path, String key) async {
    final body = _decode(await _send('GET', path));
    if (body is! Map) {
      throw ApiFailure('The server sent an answer this app cannot read.');
    }
    final csrf = body['csrf'];
    if (csrf is String) csrfToken = csrf;
    final rows = body[key];
    if (rows is! List) {
      throw ApiFailure('The server sent an answer this app cannot read.');
    }
    return rows
        .map((row) => Map<String, dynamic>.from(row as Map))
        .toList(growable: false);
  }

  Future<String> saveKot({
    int? roomId,
    String guestName = '',
    String tableNumber = '',
    bool walkIn = false,
    required List<Map<String, dynamic>> items,
    String issuedBy = '',
    String notes = '',
  }) async {
    if (csrfToken == null) {
      // Refresh: the API response carries the current token.
      await _fetchRows('/api/menu', 'menu');
    }
    final body = _decode(await _send(
      'POST',
      '/mobile/kot/save',
      headers: {'Content-Type': 'application/json; charset=utf-8'},
      body: jsonEncode({
        'mode': walkIn ? 'walkin' : 'room',
        if (walkIn) ...{
          'guest_name': guestName,
          'table_number': tableNumber,
        } else
          'room_id': roomId,
        'csrf_token': csrfToken,
        if (issuedBy.isNotEmpty) 'issued_by_name': issuedBy,
        if (notes.isNotEmpty) 'notes': notes,
        'items': items,
      }),
    ));
    if (body is Map && body['kot_number'] != null) {
      return body['kot_number'].toString();
    }
    return '';
  }

  dynamic _decode(http.Response response) {
    if (response.statusCode == 401 ||
        (response.statusCode >= 300 && response.statusCode < 400)) {
      throw SessionExpired();
    }
    if (response.statusCode != 200) {
      throw ApiFailure(
        _errorDetail(response) ?? 'Request failed (HTTP ${response.statusCode}).',
        statusCode: response.statusCode,
      );
    }
    try {
      return jsonDecode(response.body);
    } on FormatException {
      throw ApiFailure('The server sent an answer this app cannot read.',
          statusCode: response.statusCode);
    }
  }

  String? _errorDetail(http.Response response) {
    try {
      final body = jsonDecode(response.body);
      if (body is Map && body['detail'] is String) return body['detail'] as String;
    } on FormatException {
      return null;
    }
    return null;
  }
}

/// The lines of one kitchen order ticket.
class KotCart {
  final List<Map<String, dynamic>> lines = [];

  /// Tap a dish to add it, or add one more unit if it is already on the ticket.
  void add(Map<String, dynamic> item) {
    final index = lines.indexWhere((line) => line['id'] == item['id']);
    if (index >= 0) {
      lines[index]['qty'] = (lines[index]['qty'] as int) + 1;
      return;
    }
    lines.add({
      'id': item['id'],
      'catalog_id': item['id'],
      'name': item['name'] ?? 'Item',
      'rate': (item['rate'] as num?) ?? 0,
      'qty': 1,
    });
  }

  void decrement(dynamic id) {
    final index = lines.indexWhere((line) => line['id'] == id);
    if (index < 0) return;
    final remaining = (lines[index]['qty'] as int) - 1;
    if (remaining <= 0) {
      lines.removeAt(index);
    } else {
      lines[index]['qty'] = remaining;
    }
  }

  static double lineTotal(Map<String, dynamic> line) {
    final qty = ((line['qty'] as num?) ?? 0).toDouble();
    final rate = ((line['rate'] as num?) ?? 0).toDouble();
    return qty * rate;
  }

  double get total =>
      lines.fold(0.0, (sum, line) => sum + lineTotal(line));

  void clear() => lines.clear();
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, this.onSignedIn, this.notice});

  /// Hands the signed-in client to the app shell, which swaps in the KOT screen.
  final void Function(ApiClient api)? onSignedIn;

  final String? notice;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final TextEditingController _username = TextEditingController();
  final TextEditingController _password = TextEditingController();
  final ApiClient _api = ApiClient();
  bool _busy = false;
  bool _resolvingServer = true;
  String? _serverUrl;
  String? _error;

  @override
  void initState() {
    super.initState();
    _resolveServer();
  }

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _resolveServer({String? manual, bool automatic = false}) async {
    setState(() {
      _resolvingServer = true;
      _error = null;
    });
    final url = await ServerConfig.resolve(
      preferred: automatic ? null : (manual ?? _serverUrl),
    );
    if (!mounted) return;
    setState(() {
      _resolvingServer = false;
      if (url != null) {
        _serverUrl = url;
        _api.serverUrl = url;
      } else if (manual != null && manual.trim().isNotEmpty) {
        _error = 'Could not reach ${ServerConfig.normalize(manual)}. '
            'Check the address and that both devices are on the same Wi-Fi.';
      } else {
        _error = 'Could not find the server on this Wi-Fi. '
            'Tap the server address to enter it.';
      }
    });
  }

  Future<void> _askServer() async {
    final controller = TextEditingController(text: _serverUrl ?? 'http://');
    final value = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Server address'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Enter the hotel server address, for example 192.168.1.20:8000. '
              'The app remembers it for next time.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              autofocus: true,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Server',
                border: OutlineInputBorder(),
              ),
              onSubmitted: (text) => Navigator.of(context).pop(text),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(''),
            child: const Text('Find automatically'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
            child: const Text('Connect'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (value == null) return;
    await _resolveServer(manual: value, automatic: value.isEmpty);
  }

  Future<void> _signIn() async {
    final username = _username.text.trim();
    final password = _password.text;
    if (username.isEmpty || password.isEmpty) {
      setState(() => _error = 'Enter both username and password.');
      return;
    }
    if (_api.serverUrl.isEmpty) {
      await _resolveServer();
      if (_api.serverUrl.isEmpty) return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await _api.signIn(username, password);
      if (!mounted) return;
      widget.onSignedIn?.call(_api);
    } on ApiFailure catch (failure) {
      if (mounted) setState(() => _error = failure.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'Arati Hotel',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 4),
                Text(
                  'Kitchen Order Tickets',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 12),
                InkWell(
                  onTap: _resolvingServer ? null : _askServer,
                  borderRadius: BorderRadius.circular(8),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 18,
                          height: 18,
                          child: _resolvingServer
                              ? const CircularProgressIndicator(strokeWidth: 2)
                              : Icon(
                                  Icons.dns_outlined,
                                  size: 18,
                                  color: Theme.of(context).colorScheme.primary,
                                ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _resolvingServer
                                ? 'Finding the hotel server…'
                                : (_serverUrl ??
                                    'Server not found — tap to enter its address'),
                            style: const TextStyle(fontSize: 12, color: Colors.grey),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (!_resolvingServer)
                          IconButton(
                            tooltip: 'Find automatically',
                            visualDensity: VisualDensity.compact,
                            icon: const Icon(Icons.refresh, size: 18),
                            onPressed: () => _resolveServer(automatic: true),
                          ),
                        if (!_resolvingServer) const Icon(Icons.edit, size: 15, color: Colors.grey),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _username,
                  autofillHints: const [AutofillHints.username],
                  decoration: const InputDecoration(
                    labelText: 'Username',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _signIn(),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _password,
                  obscureText: true,
                  autofillHints: const [AutofillHints.password],
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _signIn(),
                ),
                const SizedBox(height: 16),
                if (widget.notice != null) ...[
                  Text(widget.notice!,
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Theme.of(context).colorScheme.primary)),
                  const SizedBox(height: 12),
                ],
                if (_error != null) ...[
                  Text(_error!,
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  const SizedBox(height: 12),
                ],
                ElevatedButton.icon(
                  onPressed: _busy ? null : _signIn,
                  icon: _busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.login),
                  label: Text(_busy ? 'Signing in…' : 'Sign in'),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class KOTScreen extends StatefulWidget {
  const KOTScreen({super.key, required this.api, required this.onSessionExpired});

  final ApiClient api;
  final VoidCallback onSessionExpired;

  @override
  State<KOTScreen> createState() => _KOTScreenState();
}

class _KOTScreenState extends State<KOTScreen> {
  bool _isLoading = true;
  bool _isConnected = true;
  bool _isSending = false;
  bool _showComposer = false;
  int? _busyKotId;
  String? _error;
  final List<Map<String, dynamic>> _rooms = [];
  final List<Map<String, dynamic>> _menu = [];
  final List<Map<String, dynamic>> _openKots = [];
  final KotCart _cart = KotCart();
  final TextEditingController _issuedBy = TextEditingController();
  final TextEditingController _notes = TextEditingController();
  final TextEditingController _guestName = TextEditingController();
  final TextEditingController _tableNumber = TextEditingController();
  bool _walkIn = false;
  int? _selectedRoomId;
  Timer? _pollTimer;
  final Set<int> _knownKotIds = {};
  final Set<String> _ignoreKotNumbers = {};
  bool _trackingKots = false;

  @override
  void initState() {
    super.initState();
    unawaited(NotificationService.instance.requestPermission());
    _loadData();
    // The kitchen board keeps itself fresh even when another phone cuts a KOT.
    _pollTimer = Timer.periodic(const Duration(seconds: 4), (_) => _refreshKots());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _issuedBy.dispose();
    _notes.dispose();
    _guestName.dispose();
    _tableNumber.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final results = await Future.wait<List<Map<String, dynamic>>>(
        [
          widget.api.fetchRooms(),
          widget.api.fetchMenu(),
          widget.api.fetchOpenKots(),
        ],
      );
      if (!mounted) return;
      setState(() {
        _rooms
          ..clear()
          ..addAll(results[0]);
        _menu
          ..clear()
          ..addAll(results[1]);
        _openKots
          ..clear()
          ..addAll(results[2]);
        _isConnected = true;
        _isLoading = false;
        if (_selectedRoomId != null &&
            !_rooms.any((room) => room['id'] == _selectedRoomId)) {
          _selectedRoomId = null;
        }
      });
      _trackKots(results[2]);
    } on SessionExpired {
      if (mounted) widget.onSessionExpired();
    } on ApiFailure catch (failure) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _isConnected = failure.statusCode != null;
        _error = failure.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
        _isConnected = false;
        _error = 'Could not load the kitchen board.';
      });
    }
  }

  /// Remembers which tickets this device has seen and alerts the first time a
  /// new one arrives. The first successful load only seeds the list.
  void _trackKots(List<Map<String, dynamic>> rows) {
    if (!_trackingKots) {
      for (final kot in rows) {
        final id = kot['id'];
        if (id is int) _knownKotIds.add(id);
      }
      _trackingKots = true;
      return;
    }
    final fresh = <Map<String, dynamic>>[];
    for (final kot in rows) {
      final id = kot['id'];
      if (id is! int || !_knownKotIds.add(id)) continue;
      final number = '${kot['kot_number'] ?? ''}';
      if (number.isNotEmpty && _ignoreKotNumbers.remove(number)) continue;
      fresh.add(kot);
    }
    if (fresh.isNotEmpty) {
      unawaited(NotificationService.instance.showNewOrders(fresh));
    }
  }

  Future<void> _refreshKots() async {
    try {
      final rows = await widget.api.fetchOpenKots();
      if (!mounted) return;
      setState(() {
        _openKots
          ..clear()
          ..addAll(rows);
        _isConnected = true;
      });
      _trackKots(rows);
    } on SessionExpired {
      if (mounted) widget.onSessionExpired();
    } on ApiFailure catch (failure) {
      if (!mounted) return;
      setState(() => _isConnected = failure.statusCode != null);
    } catch (_) {
      if (mounted) setState(() => _isConnected = false);
    }
  }

  void _addToCart(Map<String, dynamic> item) {
    setState(() => _cart.add(item));
  }

  void _decrement(dynamic id) {
    setState(() => _cart.decrement(id));
  }

  void _showNotice(String text, {bool success = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(text, style: const TextStyle(color: Colors.white)),
        backgroundColor: success ? Colors.green : Colors.red,
      ));
  }

  Future<void> _sendKOT() async {
    if (!_showComposer) {
      setState(() => _showComposer = true);
      return;
    }
    final roomId = _selectedRoomId;
    if (!_walkIn && roomId == null) {
      _showNotice('Select a room, or switch to Walk-in.');
      return;
    }
    if (_cart.lines.isEmpty) {
      _showNotice('Add items to the KOT first.');
      return;
    }

    setState(() => _isSending = true);
    try {
      final kotNumber = await widget.api.saveKot(
        roomId: roomId,
        walkIn: _walkIn,
        guestName: _guestName.text.trim(),
        tableNumber: _tableNumber.text.trim(),
        issuedBy: _issuedBy.text.trim(),
        notes: _notes.text.trim(),
        items: _cart.lines
            .map((line) => {
                  'catalog_id': line['catalog_id'],
                  'particular': line['name'],
                  'qty': line['qty'],
                  'rate': line['rate'],
                })
            .toList(),
      );
      if (kotNumber.isNotEmpty) _ignoreKotNumbers.add(kotNumber);
      if (!mounted) return;
      setState(() {
        _isSending = false;
        _isConnected = true;
        _showComposer = false;
        _cart.clear();
        _notes.clear();
        _guestName.clear();
        _tableNumber.clear();
      });
      await _refreshKots();
      _showNotice(
        kotNumber.isEmpty ? 'KOT sent to the kitchen' : 'KOT $kotNumber sent to the kitchen',
        success: true,
      );
    } on SessionExpired {
      if (mounted) widget.onSessionExpired();
    } on ApiFailure catch (failure) {
      if (!mounted) return;
      setState(() {
        _isSending = false;
        _isConnected = failure.statusCode != null;
      });
      _showNotice(failure.message);
    }
  }

  Future<bool> _confirmCut(Map<String, dynamic> kot, {bool second = false}) async {
    final number = kot['kot_number'] ?? 'KOT';
    final where = kot['room_number'] != null && '${kot['room_number']}'.isNotEmpty
        ? 'Room ${kot['room_number']}'
        : (kot['table_number'] ?? 'Walk-in');
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(second ? 'Final confirmation' : 'Cut this KOT?'),
        content: Text(
          second
              ? 'KOT $number for $where will be marked ready and your name recorded as the cook.'
              : 'Mark KOT $number for $where as ready?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Cut KOT'),
          ),
        ],
      ),
    );
    return confirmed ?? false;
  }

  Future<void> _cutKot(Map<String, dynamic> kot) async {
    if (!await _confirmCut(kot)) return;
    await _action(kot, 'ready');
  }

  Future<void> _action(Map<String, dynamic> kot, String target) async {
    final kotId = kot['id'];
    if (kotId is! int) return;
    setState(() => _busyKotId = kotId);
    var confirmed = false;
    try {
      while (true) {
        try {
          await widget.api.setKotStatus(kotId, target, confirm: confirmed);
          break;
        } on ApiFailure catch (failure) {
          // Double confirmation is on: the server wants a second yes.
          if (failure.statusCode == 428 && !confirmed) {
            if (!await _confirmCut(kot, second: true)) return;
            confirmed = true;
            continue;
          }
          rethrow;
        }
      }
      if (!mounted) return;
      _showNotice(_actionMessage(kot, target), success: true);
      await _refreshKots();
    } on SessionExpired {
      if (mounted) widget.onSessionExpired();
    } on ApiFailure catch (failure) {
      if (!mounted) return;
      _showNotice(failure.message);
      if (failure.statusCode == 409) await _refreshKots();
    } catch (_) {
      if (mounted) _showNotice('Could not update the KOT.');
    } finally {
      if (mounted) setState(() => _busyKotId = null);
    }
  }

  String _actionMessage(Map<String, dynamic> kot, String target) {
    final number = kot['kot_number'] ?? 'KOT';
    switch (target) {
      case 'preparing':
        return 'KOT $number started preparing';
      case 'ready':
        return 'KOT $number cut and marked ready';
      case 'served':
        return 'KOT $number marked served';
      default:
        return 'KOT $number updated';
    }
  }

  Future<void> _deleteKot(Map<String, dynamic> kot) async {
    final kotId = kot['id'];
    if (kotId is! int) return;
    final number = kot['kot_number'] ?? 'KOT';
    final where = kot['room_number'] != null && '${kot['room_number']}'.isNotEmpty
        ? 'Room ${kot['room_number']}'
        : (kot['table_number'] ?? 'Walk-in');
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this KOT?'),
        content: Text(
          'KOT $number for $where will be deleted and its room charges removed. '
          'This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Delete KOT'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() => _busyKotId = kotId);
    try {
      await widget.api.deleteKot(kotId);
      if (!mounted) return;
      _showNotice('KOT $number deleted', success: true);
      await _refreshKots();
    } on SessionExpired {
      if (mounted) widget.onSessionExpired();
    } on ApiFailure catch (failure) {
      if (!mounted) return;
      _showNotice(failure.message);
      if (failure.statusCode == 409) await _refreshKots();
    } catch (_) {
      if (mounted) _showNotice('Could not delete the KOT.');
    } finally {
      if (mounted) setState(() => _busyKotId = null);
    }
  }

  String _money(num value) => 'Rs. ${value.toStringAsFixed(2)}';

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(_showComposer ? 'Send KOT' : 'Kitchen Display'),
        leading: _showComposer
            ? IconButton(
                icon: const Icon(Icons.close),
                tooltip: 'Back to kitchen',
                onPressed: () => setState(() => _showComposer = false),
              )
            : null,
        actions: [
          Center(
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  _isConnected ? Icons.wifi : Icons.wifi_off,
                  color: _isConnected ? Colors.green : Colors.red,
                  size: 18,
                ),
                const SizedBox(width: 4),
                Text(
                  _isConnected ? 'Connected' : 'Offline',
                  style: TextStyle(
                    color: _isConnected ? Colors.green : Colors.red,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Padding(
            padding: const EdgeInsets.only(right: 8.0),
            child: Center(
              child: FilledButton.icon(
                onPressed: (_isConnected && !_isSending) ? _sendKOT : null,
                icon: _isSending
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Icon(_showComposer ? Icons.send : Icons.add, size: 16),
                label: Text(
                  _isSending ? 'Sending…' : 'Send KOT',
                  style: const TextStyle(fontSize: 12),
                ),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ),
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _buildErrorView()
              : _showComposer
                  ? _buildComposer(isDark)
                  : _buildBoard(isDark),
    );
  }

  Widget _buildErrorView() {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.cloud_off, size: 40, color: Colors.grey),
          const SizedBox(height: 12),
          Text(_error ?? '', textAlign: TextAlign.center),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _loadData,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildComposer(bool isDark) {
    if (_menu.isEmpty || (_rooms.isEmpty && !_walkIn)) {
      return RefreshIndicator(
        onRefresh: _loadData,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            _card(isDark, [
              Text(
                _menu.isEmpty
                    ? 'No menu items are available.'
                    : 'No rooms have a checked-in guest right now. '
                        'Swipe to refresh, or issue a walk-in KOT.',
                textAlign: TextAlign.center,
              ),
              if (_menu.isNotEmpty && _rooms.isEmpty) ...[
                const SizedBox(height: 12),
                Center(
                  child: FilledButton.icon(
                    onPressed: () => setState(() => _walkIn = true),
                    icon: const Icon(Icons.person_outline),
                    label: const Text('Walk-in (individual)'),
                  ),
                ),
              ],
              const SizedBox(height: 12),
              Center(
                child: TextButton.icon(
                  onPressed: _loadData,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Refresh'),
                ),
              ),
            ]),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _loadData,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        children: [
          _buildCustomerSection(isDark),
          const SizedBox(height: 24),
          _buildMenuSection(isDark),
          const SizedBox(height: 24),
          _buildCartSection(isDark),
          const SizedBox(height: 24),
          _buildIssueInfo(isDark),
          const SizedBox(height: 24),
          _buildTotal(isDark),
        ],
      ),
    );
  }

  Widget _buildBoard(bool isDark) {
    final groups = <String, List<Map<String, dynamic>>>{
      'new': [],
      'preparing': [],
      'ready': [],
    };
    for (final kot in _openKots) {
      groups.putIfAbsent('${kot['status']}', () => []).add(kot);
    }
    return RefreshIndicator(
      onRefresh: _loadData,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        children: [
          _buildMetrics(groups, isDark),
          const SizedBox(height: 16),
          _buildSection('New tickets', 'Waiting to start', groups['new']!,
              Colors.amber.shade800, isDark),
          const SizedBox(height: 16),
          _buildSection('Preparing', 'Cut when everything is cooked',
              groups['preparing']!, Colors.blue.shade700, isDark),
          const SizedBox(height: 16),
          _buildSection('Ready to serve', 'Mark served once collected',
              groups['ready']!, Colors.green.shade700, isDark),
        ],
      ),
    );
  }

  Widget _buildMetrics(
    Map<String, List<Map<String, dynamic>>> groups,
    bool isDark,
  ) {
    return Row(
      children: [
        _metric('New', groups['new']!.length, Colors.amber.shade800, isDark),
        const SizedBox(width: 8),
        _metric('Preparing', groups['preparing']!.length, Colors.blue.shade700, isDark),
        const SizedBox(width: 8),
        _metric('Ready', groups['ready']!.length, Colors.green.shade700, isDark),
      ],
    );
  }

  Widget _metric(String label, int count, Color color, bool isDark) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
        decoration: BoxDecoration(
          color: isDark ? Colors.grey[800] : Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: color.withValues(alpha: .35)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '$count',
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
            Text(
              label,
              style: const TextStyle(fontSize: 11, color: Colors.grey),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSection(
    String title,
    String subtitle,
    List<Map<String, dynamic>> kots,
    Color color,
    bool isDark,
  ) {
    return _card(isDark, [
      Row(
        children: [
          Container(
            width: 4,
            height: 20,
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _sectionTitle(title),
                Text(
                  subtitle,
                  style: const TextStyle(fontSize: 11, color: Colors.grey),
                ),
              ],
            ),
          ),
          Chip(
            label: Text('${kots.length}', style: const TextStyle(fontSize: 11)),
            visualDensity: VisualDensity.compact,
            padding: EdgeInsets.zero,
          ),
        ],
      ),
      const SizedBox(height: 8),
      if (kots.isEmpty)
        Text(
          'No tickets here right now.',
          style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
        )
      else
        ...kots.map((kot) => _buildKotCard(kot, color)),
    ]);
  }

  Widget _buildKotCard(Map<String, dynamic> kot, Color color) {
    final status = '${kot['status'] ?? ''}';
    final room = kot['room_number'] != null && '${kot['room_number']}'.isNotEmpty
        ? 'Room ${kot['room_number']}'
        : (kot['table_number'] ?? 'Walk-in');
    final items = kot['items'];
    final busy = _busyKotId == kot['id'];

    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: color.withValues(alpha: .35)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${kot['status_label'] ?? status}'.toUpperCase(),
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        letterSpacing: .5,
                        color: color,
                      ),
                    ),
                    Text(
                      '${kot['kot_number'] ?? 'KOT'}',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      '$room · ${kot['guest_name'] ?? 'Guest'}',
                      style: const TextStyle(fontSize: 12, color: Colors.grey),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    _money(((kot['total'] as num?) ?? 0).toDouble()),
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  Text(
                    '${kot['date'] ?? ''}',
                    style: const TextStyle(fontSize: 10, color: Colors.grey),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Issued by ${kot['issued_by_name'] ?? '—'}',
            style: const TextStyle(fontSize: 11, color: Colors.grey),
          ),
          if (items is List && items.isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              decoration: BoxDecoration(
                color: color.withValues(alpha: .06),
                borderRadius: BorderRadius.circular(8),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              child: Column(
                children: items.map((item) {
                  final row = Map<String, dynamic>.from(item as Map);
                  final amount = ((row['amount'] as num?) ?? 0).toDouble();
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${row['qty']} × ${row['particular']}',
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                        Text(
                          _money(amount),
                          style: const TextStyle(fontSize: 12),
                        ),
                      ],
                    ),
                  );
                }).toList(),
              ),
            ),
          ],
          if (kot['notes'] != null && '${kot['notes']}'.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Note: ${kot['notes']}',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Colors.amber.shade900,
              ),
            ),
          ],
          if (kot['cut_by_name'] != null &&
              '${kot['cut_by_name']}'.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Cut by ${kot['cut_by_name']} at ${kot['cut_at']}',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Colors.green,
              ),
            ),
          ],
          const SizedBox(height: 8),
          if (busy)
            const Align(
              alignment: Alignment.centerRight,
              child: SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            )
          else
            Wrap(
              spacing: 8,
              runSpacing: 4,
              alignment: WrapAlignment.end,
              children: [
                if (status == 'new')
                  OutlinedButton.icon(
                    onPressed: () => _action(kot, 'preparing'),
                    icon: const Icon(Icons.local_fire_department, size: 16),
                    label: const Text('Start preparing'),
                    style: OutlinedButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                    ),
                  ),
                if (status == 'new' || status == 'preparing')
                  FilledButton.icon(
                    onPressed: () => _cutKot(kot),
                    icon: const Icon(Icons.check_circle, size: 16),
                    label: const Text('Cut KOT'),
                    style: FilledButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                    ),
                  ),
                if (status == 'ready')
                  FilledButton.icon(
                    onPressed: () => _action(kot, 'served'),
                    icon: const Icon(Icons.restaurant, size: 16),
                    label: const Text('Mark served'),
                    style: FilledButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                    ),
                  ),
                OutlinedButton.icon(
                  onPressed: () => _deleteKot(kot),
                  icon: const Icon(Icons.delete_outline, size: 16),
                  label: const Text('Delete KOT'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.red.shade700,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _card(bool isDark, List<Widget> children) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: isDark ? Colors.grey[800] : Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: const [
          BoxShadow(
            color: Colors.black12,
            blurRadius: 4,
            offset: Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    );
  }

  Widget _sectionTitle(String text) => Text(
        text,
        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
      );

  Widget _buildCustomerSection(bool isDark) {
    return _card(isDark, [
      _sectionTitle('Customer'),
      const SizedBox(height: 8),
      Wrap(
        spacing: 8,
        children: [
          ChoiceChip(
            label: const Text('Room guest'),
            selected: !_walkIn,
            onSelected: (_) => setState(() => _walkIn = false),
          ),
          ChoiceChip(
            label: const Text('Walk-in (individual)'),
            selected: _walkIn,
            onSelected: (_) => setState(() => _walkIn = true),
          ),
        ],
      ),
      const SizedBox(height: 8),
      if (_walkIn) ...[
        TextField(
          controller: _guestName,
          textCapitalization: TextCapitalization.words,
          decoration: InputDecoration(
            labelText: 'Customer name',
            hintText: 'e.g. Sita Sharma',
            border: const OutlineInputBorder(),
            filled: true,
            fillColor: isDark ? Colors.grey[700] : Colors.grey[100],
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _tableNumber,
          decoration: InputDecoration(
            labelText: 'Table / seat (optional)',
            hintText: 'e.g. Table 3',
            border: const OutlineInputBorder(),
            filled: true,
            fillColor: isDark ? Colors.grey[700] : Colors.grey[100],
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'Walk-in tickets are paid at the counter; nothing is posted to a room folio.',
          style: TextStyle(fontSize: 12, color: Colors.grey),
        ),
      ] else
        _roomDropdown(isDark),
    ]);
  }

  Widget _roomDropdown(bool isDark) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        border: Border(
          left: BorderSide(
            color: isDark ? const Color(0xFF757575) : const Color(0xFFB0B0B0),
            width: 2,
          ),
        ),
        borderRadius: BorderRadius.circular(8),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<int>(
          value: _selectedRoomId,
          hint: const Text('Choose a room'),
          isExpanded: true,
          items: _rooms.map((room) {
            return DropdownMenuItem<int>(
              value: room['id'] as int,
              child: Text(
                'Room ${room['number']} - ${room['guest_name']}',
                style: const TextStyle(fontSize: 14),
              ),
            );
          }).toList(),
          onChanged: (value) => setState(() => _selectedRoomId = value),
        ),
      ),
    );
  }

  Widget _buildMenuSection(bool isDark) {
    return _card(isDark, [
      _sectionTitle('Menu'),
      const SizedBox(height: 8),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: _menu.map((item) {
          return FilterChip(
            label: Text(item['name'] ?? 'Item'),
            selected: false,
            onSelected: (_) => _addToCart(item),
            backgroundColor: isDark ? Colors.grey[800] : Colors.white,
          );
        }).toList(),
      ),
    ]);
  }

  Widget _buildCartSection(bool isDark) {
    return _card(isDark, [
      _sectionTitle('This KOT'),
      const SizedBox(height: 8),
      if (_cart.lines.isEmpty)
        const Text('No items added', style: TextStyle(color: Colors.grey))
      else
        ..._cart.lines.map((line) => ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text(line['name'] ?? 'Item'),
              subtitle: Text('${line['qty']} × ${_money((line['rate'] as num?) ?? 0)}'),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    _money(KotCart.lineTotal(line)),
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  IconButton(
                    icon: const Icon(Icons.remove_circle_outline),
                    tooltip: 'Remove one',
                    onPressed: () => _decrement(line['id']),
                  ),
                ],
              ),
            )),
    ]);
  }

  Widget _buildIssueInfo(bool isDark) {
    return _card(isDark, [
      _sectionTitle('Issue Details'),
      const SizedBox(height: 8),
      TextField(
        controller: _issuedBy,
        decoration: InputDecoration(
          labelText: 'Issued by',
          border: const OutlineInputBorder(),
          filled: true,
          fillColor: isDark ? Colors.grey[700] : Colors.grey[100],
        ),
      ),
      const SizedBox(height: 8),
      TextField(
        controller: _notes,
        decoration: InputDecoration(
          labelText: 'Kitchen note (optional)',
          border: const OutlineInputBorder(),
          filled: true,
          fillColor: isDark ? Colors.grey[700] : Colors.grey[100],
        ),
      ),
    ]);
  }

  Widget _buildTotal(bool isDark) {
    return _card(isDark, [
      Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          _sectionTitle('Total'),
          Text(
            _money(_cart.total),
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
              color: Theme.of(context).colorScheme.primary,
            ),
          ),
        ],
      ),
    ]);
  }

}
