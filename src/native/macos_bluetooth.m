// TripleSense's owned Bluetooth HID transport. No firmware or pairing writes.
// IPC: little-endian uint32 length, uint8 kind, uint32 request, payload.
// Commands: 1=GET_FEATURE, 2=OUTPUT, 3=SET_FEATURE, 4=CLOSE.
// Responses: 0=ready, 1=feature, 2/3=ack, 16=input, 255=error.
#import <AppKit/AppKit.h>
#import <CoreBluetooth/CoreBluetooth.h>
#import <IOBluetooth/IOBluetooth.h>
#import <objc/message.h>
#include <errno.h>
#include <signal.h>
#include <unistd.h>

static id getObject(id object, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    return [object respondsToSelector:selector]
        ? ((id(*)(id, SEL))objc_msgSend)(object, selector) : nil;
}
static BOOL readAll(int fd, void *buffer, size_t length) {
    uint8_t *p = buffer;
    while (length) {
        ssize_t n = read(fd, p, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return NO;
        p += n; length -= n;
    }
    return YES;
}
static void reply(uint8_t kind, uint32_t request, NSData *data) {
    uint32_t length = (uint32_t)data.length;
    uint8_t header[9] = {length, length >> 8, length >> 16, length >> 24,
                        kind, request, request >> 8, request >> 16, request >> 24};
    NSMutableData *message = [NSMutableData dataWithBytes:header length:9];
    [message appendData:data];
    const uint8_t *p = message.bytes; size_t left = message.length;
    while (left) {
        ssize_t n = write(STDOUT_FILENO, p, left);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) _exit(1);
        p += n; left -= n;
    }
}

@interface Transport : NSObject<CBCentralManagerDelegate, NSStreamDelegate>
@property CBCentralManager *central;
@property IOBluetoothDevice *device;
@property id peer;
@property CBL2CAPChannel *control;
@property CBL2CAPChannel *interrupt;
@property NSString *address;
@property NSMutableData *inputBytes;
@property NSMutableData *featureBytes;
@property NSMutableArray<NSDictionary *> *controlQueue;
@property NSMutableArray<NSDictionary *> *outputQueue;
@property NSDictionary *activeControl;
@property NSUInteger featureGeneration;
@property BOOL starting;
@property BOOL ready;
@property BOOL stopping;
@end

@implementation Transport
- (void)error:(NSString *)message request:(uint32_t)request {
    reply(255, request, [message dataUsingEncoding:NSUTF8StringEncoding]);
}
- (void)finish {
    if (self.stopping) return;
    self.stopping = YES;
    for (CBL2CAPChannel *c in @[self.control ?: (id)NSNull.null,
                                self.interrupt ?: (id)NSNull.null]) {
        if ((id)c == NSNull.null) continue;
        c.inputStream.delegate = nil; c.outputStream.delegate = nil;
        [c.inputStream close]; [c.outputStream close];
    }
    [NSApp terminate:nil];
}
- (void)fail:(NSString *)message {
    [self error:message request:0]; [self finish];
}
- (void)centralManagerDidUpdateState:(CBCentralManager *)central {
    if (central.state == CBManagerStateUnauthorized) {
        [self fail:@"Allow Bluetooth access for TripleSense in macOS Settings."]; return;
    }
    if (central.state != CBManagerStatePoweredOn || self.starting) return;
    self.starting = YES;
    // IOBluetooth's first initialization must not block the main queue it uses.
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        IOBluetoothDevice *device = [IOBluetoothDevice deviceWithAddressString:self.address];
        dispatch_async(dispatch_get_main_queue(), ^{
            if (self.stopping) return;
            self.device = device;
            self.peer = getObject(device, @"classicPeer");
            if (!self.peer || ![self.peer respondsToSelector:NSSelectorFromString(@"setConnectL2CAPCallback:")]) {
                [self fail:@"This macOS version does not provide the native Bluetooth transport."]; return;
            }
            // Release this controller's system HID profile, retaining its pairing.
            [device closeConnection];
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 350 * NSEC_PER_MSEC),
                           dispatch_get_main_queue(), ^{ [self openControl]; });
        });
    });
}
- (void)openControl {
    if (self.stopping) return;
    __weak Transport *weakSelf = self;
    // The legacy IOBluetoothL2CAPChannel initializer prematurely disposes of its
    // asynchronously-created channel on current macOS. Retain the actual channel.
    void (^opened)(id) = ^(id object) {
        if (![object isKindOfClass:CBL2CAPChannel.class]) return;
        CBL2CAPChannel *channel = object;
        dispatch_async(dispatch_get_main_queue(), ^{
            Transport *owner = weakSelf;
            if (!owner || owner.stopping) return;
            if (channel.PSM == 0x11) owner.control = channel;
            else if (channel.PSM == 0x13) owner.interrupt = channel;
            else return;
            for (NSStream *stream in @[channel.inputStream, channel.outputStream]) {
                stream.delegate = owner;
                [stream scheduleInRunLoop:NSRunLoop.mainRunLoop forMode:NSDefaultRunLoopMode];
                [stream open];
            }
            if (channel.PSM == 0x11) {
                ((void(*)(id, SEL, unsigned short))objc_msgSend)(owner.peer,
                    NSSelectorFromString(@"openL2CAPChannel:"), 0x13);
            } else {
                owner.ready = YES; reply(0, 0, NSData.data);
            }
        });
    };
    ((void(*)(id, SEL, id))objc_msgSend)(self.peer,
        NSSelectorFromString(@"setConnectL2CAPCallback:"), opened);
    ((void(*)(id, SEL, unsigned short))objc_msgSend)(self.peer,
        NSSelectorFromString(@"openL2CAPChannel:"), 0x11);
}
- (void)flushOutput {
    while (self.outputQueue.count && self.interrupt.outputStream.hasSpaceAvailable) {
        NSDictionary *command = self.outputQueue.firstObject;
        NSData *data = command[@"data"];
        NSInteger n = [self.interrupt.outputStream write:data.bytes maxLength:data.length];
        if (n < 0 || (NSUInteger)n != data.length) { [self fail:@"Bluetooth output stream could not send a complete report."]; return; }
        reply(2, [command[@"request"] unsignedIntValue], NSData.data);
        [self.outputQueue removeObjectAtIndex:0];
    }
}
- (void)flushControl {
    if (self.activeControl || !self.controlQueue.count || !self.control.outputStream.hasSpaceAvailable) return;
    self.activeControl = self.controlQueue.firstObject;
    [self.controlQueue removeObjectAtIndex:0];
    self.featureBytes = NSMutableData.data;
    NSData *data = self.activeControl[@"data"];
    NSInteger n = [self.control.outputStream write:data.bytes maxLength:data.length];
    if (n < 0 || (NSUInteger)n != data.length) { [self fail:@"Bluetooth control stream could not send a complete request."]; return; }
    NSDictionary *pending = self.activeControl;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (self.activeControl == pending && !self.stopping) {
            [self error:@"Controller feature request timed out." request:[pending[@"request"] unsignedIntValue]];
            // A late reply cannot safely be attributed to a subsequent request.
            [self finish];
        }
    });
}
- (void)controlData:(NSData *)data {
    if (!self.activeControl) return;
    [self.featureBytes appendData:data];
    if (self.featureBytes.length > 4096) { [self fail:@"Invalid Bluetooth control response."]; return; }
    NSUInteger generation = ++self.featureGeneration;
    // NSStreams may split one SDU into reads. Only one control request is in
    // flight; collect the remaining bytes before completing that transaction.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
        if (self.stopping || generation != self.featureGeneration || !self.activeControl) return;
        const uint8_t *b = self.featureBytes.bytes;
        uint32_t request = [self.activeControl[@"request"] unsignedIntValue];
        uint8_t kind = [self.activeControl[@"kind"] unsignedCharValue];
        if (kind == 1 && self.featureBytes.length > 1 && b[0] == 0xa3 &&
            b[1] == [self.activeControl[@"report"] unsignedCharValue]) {
            reply(1, request, [self.featureBytes subdataWithRange:NSMakeRange(1, self.featureBytes.length - 1)]);
        } else if (kind == 3 && self.featureBytes.length == 1 && b[0] == 0) {
            reply(3, request, NSData.data);
        } else [self error:@"Controller rejected the feature request." request:request];
        self.activeControl = nil; [self flushControl];
    });
}
- (void)stream:(NSStream *)stream handleEvent:(NSStreamEvent)event {
    if (self.stopping) return;
    if (event & (NSStreamEventErrorOccurred | NSStreamEventEndEncountered)) {
        [self fail:@"DualSense Bluetooth connection closed."]; return;
    }
    if (event & NSStreamEventHasSpaceAvailable) { [self flushControl]; [self flushOutput]; }
    if (!(event & NSStreamEventHasBytesAvailable)) return;
    NSInputStream *input = (NSInputStream *)stream;
    while (input.hasBytesAvailable) {
        uint8_t b[4096]; NSInteger n = [input read:b maxLength:sizeof(b)];
        if (n <= 0) break;
        NSData *data = [NSData dataWithBytes:b length:n];
        if (stream == self.control.inputStream) [self controlData:data];
        else {
            // Send stream chunks to Python, which validates CRCs and reassembles
            // the 79-byte HIDP reports before exposing HIDAPI-compatible input.
            reply(16, 0, data);
        }
    }
}
- (void)command:(uint8_t)kind request:(uint32_t)request data:(NSData *)payload {
    if (kind == 4) { [self finish]; return; }
    if (!self.ready || self.stopping) { [self error:@"Bluetooth transport is not connected." request:request]; return; }
    const uint8_t *b = payload.bytes;
    if (kind == 2 && payload.length >= 1 && payload.length <= 547 && b[0] >= 0x31 && b[0] <= 0x39) {
        NSMutableData *wire = [NSMutableData dataWithBytes:"\xa2" length:1]; [wire appendData:payload];
        if (self.outputQueue.count >= 32) { [self error:@"Bluetooth output queue is full." request:request]; return; }
        [self.outputQueue addObject:@{@"request":@(request), @"data":wire}]; [self flushOutput];
    } else if (kind == 1 && payload.length == 1) {
        if (self.controlQueue.count >= 16) { [self error:@"Bluetooth control queue is full." request:request]; return; }
        uint8_t get[] = {0x43, b[0]};
        [self.controlQueue addObject:@{@"request":@(request), @"kind":@1, @"report":@(b[0]),
                                      @"data":[NSData dataWithBytes:get length:2]}]; [self flushControl];
    } else if (kind == 3 && payload.length > 1 && payload.length <= 547 &&
               (b[0] == 0x80 || (b[0] == 0x08 && b[1] == 0x02))) {
        if (self.controlQueue.count >= 16) { [self error:@"Bluetooth control queue is full." request:request]; return; }
        NSMutableData *wire = [NSMutableData dataWithBytes:"\x53" length:1]; [wire appendData:payload];
        [self.controlQueue addObject:@{@"request":@(request), @"kind":@3, @"data":wire}]; [self flushControl];
    } else [self error:@"Unsupported Bluetooth transport command." request:request];
}
@end

Transport *TripleSenseStartTransport(NSString *address) {
    Transport *transport = Transport.new;
    transport.address = address;
    transport.controlQueue = NSMutableArray.new; transport.outputQueue = NSMutableArray.new;
    transport.central = [[CBCentralManager alloc] initWithDelegate:transport queue:dispatch_get_main_queue()
        options:@{CBCentralManagerOptionShowPowerAlertKey:@NO}];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 20 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (!transport.ready && !transport.stopping) [transport fail:@"Could not open DualSense Bluetooth. Press PS and retry."];
    });
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        for (;;) {
            uint8_t h[9]; if (!readAll(STDIN_FILENO, h, 9)) break;
            uint32_t n = h[0] | (uint32_t)h[1]<<8 | (uint32_t)h[2]<<16 | (uint32_t)h[3]<<24;
            uint32_t request = h[5] | (uint32_t)h[6]<<8 | (uint32_t)h[7]<<16 | (uint32_t)h[8]<<24;
            if (n > 4096) break;
            NSMutableData *data = [NSMutableData dataWithLength:n];
            if (n && !readAll(STDIN_FILENO, data.mutableBytes, n)) break;
            uint8_t kind = h[4];
            dispatch_async(dispatch_get_main_queue(), ^{ [transport command:kind request:request data:data]; });
        }
        dispatch_async(dispatch_get_main_queue(), ^{ [transport finish]; });
    });
    return transport;
}

int main(int argc, char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    if (!strcmp(argv[1], "--version")) { puts("TripleSense native Bluetooth transport 1"); return 0; }
    signal(SIGPIPE, SIG_IGN);
    [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    [NSApp finishLaunching];
    Transport *transport = TripleSenseStartTransport([NSString stringWithUTF8String:argv[1]]);
    [NSApp run]; (void)transport;
    return 0;
}}
