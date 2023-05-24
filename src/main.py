import sys
import pandas as pd
import socket
import select
import threading as th
import random
import time

TIMEOUT = 30
GARBAGECOLLECTION = 20
UPDATE = 5
IP = '127.0.0.1'

class Router:
    '''
        Router class
    '''
    def __init__(self, router_id, inputs, outputs):
        self.router_id = router_id
        self.inputs = inputs
        self.outputs = outputs
        self.routing_table = self.generate_routing_table(outputs)
        self.update_timer = Timer(self.update, self.random_period_generator(), ())
        self.update_timer.start()

    def generate_routing_table(self, outputs):
        self.routing_table = {}
        self.routing_table[self.router_id] = {'dest': self.router_id, 'metric': 0,
                'next_hop': 0,'flag': False, 'timers': None}
        for output in outputs:
            entry = {'dest': output[2], 'metric': output[1],
                'next_hop': output[2], 'flag': False, 'timers': Timer(self.timeout, TIMEOUT, (output[2],))}
            entry['timers'].start()
            self.routing_table[output[2]] = entry
        return self.routing_table
    
    def random_period_generator(self):
        return random.randint(0.8*UPDATE, 1.2*UPDATE)

    def generate_response(self, destination, index):
        entries = ''
        entries += self.to_binary(1, 8)
        entries += self.to_binary(2, 8)
        entries += self.to_binary(self.router_id, 16)
        for entry in self.routing_table.values():
            entries += self.to_binary(2, 16)
            entries += self.to_binary(0, 16)
            entries += self.to_binary(entry['dest'], 32)
            entries += self.to_binary(0, 32)
            entries += self.to_binary(0, 32)
            if destination == entry['next_hop']:
                entries += self.to_binary(16, 32)
            elif entry['dest'] == self.router_id:
                entries += self.to_binary(self.outputs[index][1], 32)
            else:
                entries += self.to_binary(entry['metric'], 32) 

        integer = int(entries, 2)
        packet = bytearray()
        while integer:
            packet.append(integer & 0xFF)
            integer >>= 8
        packet = packet[::-1]
        return packet

    def validate_response(self, response):
        resp_hex = response.hex()
        if resp_hex[0:2] != '01':
            return 'Error incorrect command id'
        if resp_hex[2:4] != '02':
            return 'Error incorrect version number'
        if int(resp_hex[4:8], 16) < 1 or int(resp_hex[4:8], 16) > 64000:
            return 'Error incorrect router id'
        entries = resp_hex[8:]
        i = 0
        while i < len(entries):
            entry = entries[i: i+40]
            if entry[0:4] != '0002':
                return 'Error incorrect family value'
            if int(entry[32:], 16) < 1 or int(entry[32:], 16) > 16:
                return 'Error invalid metric'
            i += 40
        return 'VALID'

    def process_input(self, packet):
        resp_hex = packet.hex()
        router_id = int(resp_hex[4:8], 16)
        entries = resp_hex[8:]
        routes = []
        i = 0
        while i < len(entries):
            entry = entries[i: i+40]
            dest = int(entry[8:16], 16)
            metric = int(entry[32:], 16)
            routes.append({'dest': dest, 'metric': metric})
            i += 40
        return router_id, routes
    
    def update_routing_table(self, updates):
        '''
            Class to update the routing table based on an update method
            If a new router is to be added to the table a new record is created with all necessary details and a timeout timer.
            The timeout timer of the sending router is restarted without updating the metric.
            If the sending router is the next hop the updated metric is always accepted as the new value. If this value is greater than 16 a garbage collection timer is started
            If the sending router is not the current next hop and the metric is less than the current metric value then the sending router is selected as the next hop and the new metric accepted
            The timeout timer is restarted for all entries in the routing table.
        '''
        router_id, routes = updates
        for entry in routes:
            dest = entry['dest']
            if dest != self.router_id:
                if router_id not in self.routing_table:
                    new_metric = min(entry['metric'], 16)
                else:
                    new_metric = min(entry['metric'] + self.routing_table[router_id]['metric'], 16)

                if dest not in self.routing_table:
                    if new_metric != 16:
                        self.routing_table[dest] = {'dest': dest, 'metric': new_metric, 'next_hop': router_id, 'flag': False, 'timers': Timer(self.timeout, TIMEOUT, (dest,))}
                        self.routing_table[dest]['timers'].start()
                else:
                    route = self.routing_table[dest]
                    if router_id == route['dest']:
                        route['timers'].cancel()
                        route['timers'] = Timer(self.timeout, TIMEOUT, (dest,))
                        route['timers'].start()
                    elif router_id == route['next_hop']:
                        if entry['metric'] != route['metric']:
                            if route['metric'] != 16 and entry['metric'] >= 16:
                                route['metric'] = 16
                                route['timers'].cancel()
                                route['timers'] = Timer(self.garbage_collection, GARBAGECOLLECTION, (dest,))
                                route['timers'].start()
                            else:
                                route['next_hop'] = router_id
                                route['metric'] = new_metric
                                route['timers'].cancel()
                                route['timers'] = Timer(self.timeout, TIMEOUT, (dest,))
                                route['timers'].start()
                        elif route['metric'] != 16:
                            route['timers'].cancel()
                            route['timers'] = Timer(self.timeout, TIMEOUT, (dest,))
                            route['timers'].start()
                    elif new_metric < route['metric']:
                        route['next_hop'] = router_id
                        route['metric'] = new_metric
                        route['timers'].cancel()
                        route['timers'] = Timer(self.timeout, TIMEOUT, (dest,))
                        route['timers'].start()
        print(self) 
        

    def update(self):
        i = 0
        for output in self.outputs:
            response = self.generate_response(output[2], i)
            try: 
                self.inputs[0].sendto(response, (IP, output[0]))
            except:
                print("Could not send response")
            i += 1
        self.update_timer = Timer(self.update, self.random_period_generator(), ())
        self.update_timer.start()

    def to_binary(self, number, length):
        return_bin = bin(number)[2:]

        if return_bin[0] == 'b':
            return_bin = return_bin[1:]
        while len(return_bin) < length:
            return_bin = '0' + return_bin
        return return_bin
    
    def timeout(self, router_id):
        if router_id in self.routing_table:
            self.routing_table[router_id]['timers'].cancel()
            self.routing_table[router_id]['timers'] = Timer(self.garbage_collection, GARBAGECOLLECTION, (router_id,))
            self.routing_table[router_id]['timers'].start()
            self.routing_table[router_id]['metric'] = 16
            self.update()
            print(self) 
        return
                
    
    def garbage_collection(self, router_id):
        if router_id in self.routing_table:
            del self.routing_table[router_id]
            print(self)
        return
    
    def __repr__(self):
        routing_table = self.routing_table
    
        router_name = f'\n\n---------------------ROUTER {self.router_id}---------------------\n'

        header = 'DESTINATION | METRIC | NEXT HOP |       TIMER'
        table = ''

        for router in sorted(routing_table):
            metric = routing_table[router]['metric']
            if metric < 10:
                metric = str(metric) + ' '
            table += f"\n     {routing_table[router]['dest']}      |   {metric}   |    {routing_table[router]['next_hop']}     |  {routing_table[router]['timers']}"

        return router_name + header + table

                


class Timer:
    '''
        Class for timer objects used in the router
    '''
    def __init__(self, task, time, args):
        self.timer = th.Timer(time, task, args=args)
        self.start_time = 0.00
        if time == TIMEOUT:
            self.type = 'TIMEOUT'
        elif time == GARBAGECOLLECTION:
            self.type = 'GARBAGECOLLECTION'
        elif time == UPDATE:
            self.type = 'UPDATE'
    
    def start(self):
        self.timer.start()
        self.start_time = time.perf_counter()
    
    def cancel(self):
        self.timer.cancel()

    def __repr__(self):
            return f"{self.type}: {(time.perf_counter() - self.start_time):.2f}"


def valid_config(router, inputs, outputs):
    '''
        Confirm that the config file has a valid structure
    '''
    if not router.isdigit() or int(router) < 1 or int(router) > 64000:
        return False
    for input in inputs:
        if not input.isdigit() or int(input) < 1024 or int(input) > 64000:
            return False
    for output in outputs:
        if not output[0].isdigit() or int(output[0]) < 1024 or int(output[0]) > 64000 or (output[0] in inputs):
            return False
        if not output[1].isdigit() or int(output[1]) < 1 or int(output[1]) > 16:
            return False
        if not output[2].isdigit() or int(output[2]) < 1 or int(output[2]) > 64000:
            return False
    return True


def read_input(filename):
    '''
        Read the config file and creates an instance of the router class
    '''
    df = pd.read_csv(filename, header=None, index_col=0).squeeze("columns")
    d = df.to_dict()
    try:
        router_id = d['ROUTER_ID']
        inputs = d['INPUTS'].split(' ')
        outputs = d['OUTPUTS'].split(' ')
        outputs = [output.split('-') for output in outputs]
    except:
        print("Invalid config file format")
        sys.exit()

    if not valid_config(router_id, inputs, outputs):
        print("Invalid config file")
        sys.exit()

    router_id = int(router_id)
    inputs = list(map(int, inputs))
    outputs = [list(map(int, output)) for output in outputs]
    input_sockets = []
    for input in inputs:
        input_sockets.append(bind_socket(input))
    return Router(router_id, input_sockets, outputs)


def handle_response(router, bytestream):
    '''
        Handle a response message from a neighbouring router
    '''
    response_valid = router.validate_response(bytestream)
    if response_valid != 'VALID':
        print(response_valid)
    else:
        updates = router.process_input(bytestream)
        router.update_routing_table(updates)
        


def bind_socket(port_number):
    '''
        Create a socket and bind it to the provided port number.
        Return the created socket.
        Handle all errors related to creating a socket and print a relevant error message to the terminal
    '''
    try:
        socket_to_bind = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except:
        print('Failed to create socket')
        sys.exit()
    try:
        socket_to_bind.bind(('', port_number))
    except socket.error:
        print('Failed to bind socket to the port number')
        sys.exit()
    return socket_to_bind


def main():
    filename = sys.argv[1]
    router = read_input(filename)
    print(router)



    while (1):
        potential_readers = router.inputs
        potential_writers = router.inputs
        potential_errs = []
        reader, writer, errors = select.select(
            potential_readers, potential_writers, potential_errs)
        if len(reader) > 0:
            for socket in router.inputs:
                if socket in reader:
                    bytestream, (ip, port) = socket.recvfrom(1024)
                    handle_response(router, bytestream)





main()
