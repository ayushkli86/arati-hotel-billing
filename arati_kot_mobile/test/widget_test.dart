import 'package:flutter_test/flutter_test.dart';

import 'package:arati_kot_mobile/main.dart';

void main() {
  test('normalize fills in the server port and drops paths', () {
    expect(ServerConfig.normalize('arati.local'), 'http://arati.local:8000');
    expect(
      ServerConfig.normalize('http://100.75.70.149:8000/healthz'),
      'http://100.75.70.149:8000',
    );
    expect(ServerConfig.normalize('  '), '');
  });
}
